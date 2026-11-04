"""Batch offline replay of all EARLIER_STATE_CORRUPTION stateguard checkpoints
through the current (new causal-context) guard prompt, comparing old vs new
root predictions against ground truth (phase-11.3). No OSWorld execution."""

from __future__ import annotations

import glob
import json
import argparse
from pathlib import Path

from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.schema import ActionProposal
from stateguard.core.task_state import VerifiedTaskState
from stateguard.guard.backends.mllm_backend import MLLMBackend
from stateguard.guard.localization import earliest_failed_ancestor_selection
from stateguard.interfaces.observation import Observation
from stateguard.models import create_model_client, load_model_config

LEGACY_ROOTS = {
    "030eeff7-b492-4218-b312-701ec99ee0cc": "S2",
    "3680a5ee-6870-426a-a997-eba929a0d25c": "S2",
    "4127319a-8b79-4410-b58a-7a151e15f3d7": "S2",
    "8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14": "S2",
    "99146c54-4f37-4ab8-9327-5f3291665e1e": "S2",
    "d53ff5ee-3b1a-431e-b2be-30ed2673079b": "S3",
}


def _ground_truth(traj: str, task_id: str) -> str | None:
    fault_path = Path(traj).with_name("fault_spec.json")
    if fault_path.exists():
        return json.loads(fault_path.read_text(encoding="utf-8")).get("root_node")
    return LEGACY_ROOTS.get(task_id)


def main():
    parser = argparse.ArgumentParser(description="Replay earlier-corruption diagnosis")
    parser.add_argument(
        "--trajectory-glob",
        default=(
            "/data/research/stateguard_runs/poc_v1_108/"
            "osworld_stateguard_poc-stateguard/episodes/"
            "*--earlier_state_corruption--*/trajectory.jsonl"
        ),
    )
    parser.add_argument("--models", default="configs/models.yaml")
    parser.add_argument("--provider", default="stateguard_api")
    parser.add_argument("--report")
    args = parser.parse_args()

    client = create_model_client(load_model_config(args.models)[args.provider])
    backend = MLLMBackend(client, max_parse_retries=1)
    episodes = sorted(glob.glob(args.trajectory_glob, recursive=True))
    if not episodes:
        raise SystemExit(f"no trajectories matched: {args.trajectory_glob}")
    results = []
    for traj in episodes:
        tid = traj.split("/")[-2].split("--")[0]
        gt = _ground_truth(traj, tid)
        rows = [json.loads(line) for line in open(traj)]
        new_preds = []
        old_preds = []
        trust = {}
        replay_error = None
        injected = next((d for d in rows if d.get("injected_fault")), None)
        if injected is None:
            results.append({"task_id": tid, "ground_truth": gt, "old_first": None,
                            "new_first": None, "match": False, "valid": False})
            print(f"{tid[:8]} GT={gt} invalid_injection=no matching action was injected")
            continue
        exposed = next((d for d in rows if d.get("failure_exposure")), None)
        diagnostic = next(
            (d for d in rows
             if d["step"] >= injected["step"]
             and (d.get("guard_result") or {}).get("judgement") == "contradicted"),
            None) or exposed
        if diagnostic is None:
            diagnostic = next(
                (d for d in reversed(rows)
                 if d["step"] >= injected["step"] and d.get("guard_result")), None)
        for d in rows:
            g = d.get("guard_result") or {}
            if g.get("fault_root"):
                old_preds.append(g["fault_root"])
        if diagnostic is not None:
            d = diagnostic
            try:
                state = VerifiedTaskState.deserialize(d["task_state_before"])
                graph = DependencyGraph.from_state(state)
                active = (d.get("executor_proposal") or {}).get("subgoal_id")
                candidates = graph.ancestors(active) + [active]
                before = Observation.from_dict(d["observation_before"])
                after = Observation.from_dict(d["observation_after"])
                proposal = ActionProposal.from_dict(d["executor_proposal"])
                trace_window = []
                for prior in rows:
                    if prior["step"] > d["step"]:
                        break
                    p = prior.get("executor_proposal") or {}
                    if p.get("subgoal_id") in candidates:
                        trace_window.append({
                            "step_id": prior["step"],
                            "active_node_id": p.get("subgoal_id"),
                            "executor_intent": p.get("intent"),
                            "proposed_action": p.get("action"),
                            "action": prior.get("executed_action") or p.get("action"),
                            "expected_effect": p.get("expected_effect"),
                            "state_before": prior.get("task_state_before"),
                        })
                trust = backend.diagnose_candidates(
                    state, before, proposal, after, candidates, trace_window)
                new_preds.append(
                    earliest_failed_ancestor_selection(candidates, trust))
            except Exception as exc:
                replay_error = f"{type(exc).__name__}: {exc}"
                new_preds.append(f"ERR:{replay_error}")
        old_first = old_preds[0] if old_preds else None
        new_first = new_preds[0] if new_preds else None
        ok = "YES" if new_first == gt else "no"
        results.append({"task_id": tid, "ground_truth": gt, "old_first": old_first,
                        "new_first": new_first, "match": new_first == gt,
                        "valid": True, "diagnostic_step": diagnostic["step"]
                        if diagnostic else None, "trust": trust,
                        "error": replay_error})
        print(f"{tid[:8]} GT={gt} checkpoint={diagnostic['step'] if diagnostic else None} "
              f"old_first={old_first} new_first={new_first} trust={trust if diagnostic else {}} "
              f"match={ok}")
    correct = sum(1 for result in results if result["match"])
    valid = sum(1 for result in results if result["valid"])
    print(f"\nnew-prompt First Root Accuracy (earlier): {correct}/{len(results)}")
    print(f"valid-injection First Root Accuracy: {correct}/{valid}")
    report = {"episodes": len(results), "valid_injections": valid, "correct": correct,
              "accuracy_all": correct / len(results),
              "accuracy_valid": correct / valid if valid else 0, "results": results}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
