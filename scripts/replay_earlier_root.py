"""Offline replay of a saved episode's guard checkpoints through the CURRENT
(new causal-context) guard prompt, to compare old vs new root predictions
against ground truth. Does NOT execute OSWorld (phase-11)."""

from __future__ import annotations

import json
import sys

from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.schema import ActionProposal
from stateguard.core.task_state import VerifiedTaskState
from stateguard.guard.backends.mllm_backend import MLLMBackend
from stateguard.guard.parser import parse_guard_output
from stateguard.guard.localization import earliest_failed_ancestor_selection
from stateguard.interfaces.observation import Observation
from stateguard.models import create_model_client, load_model_config

TRAJ = ("/data/research/stateguard_runs/poc_sparse_fault_smoke/osworld_sparse_fault_smoke-stateguard/"
        "episodes/d53ff5ee-3b1a-431e-b2be-30ed2673079b--stateguard--"
        "d53ff5ee-3b1a-431e-b2be-30ed2673079b--earlier_state_corruption--1/trajectory.jsonl")
GT_ROOT = "S3"  # injected root for the Writer earlier corruption
OLD_PRED = "S4"


def main():
    client = create_model_client(load_model_config("configs/models.yaml")["stateguard_api"])
    backend = MLLMBackend(client, max_parse_retries=1)
    rows = [json.loads(line) for line in open(TRAJ)]
    print(f"GT root = {GT_ROOT}, old prediction = {OLD_PRED}")
    for d in rows:
        g = d.get("guard_result") or {}
        if g.get("judgement") != "contradicted":
            continue
        step = d["step"]
        state = VerifiedTaskState.deserialize(d["task_state_before"])
        graph = DependencyGraph.from_state(state)
        active = (d.get("executor_proposal") or {}).get("subgoal_id")
        candidates = graph.ancestors(active) + [active]
        before = Observation.from_dict(d["observation_before"])
        after = Observation.from_dict(d["observation_after"])
        proposal = ActionProposal.from_dict(d["executor_proposal"])
        try:
            result = backend.verify(state, before, proposal, after,
                                    checkpoint_kind="completion",
                                    candidate_nodes=candidates)
            trust = backend.diagnose_candidates(
                state, before, proposal, after, candidates)
            new_pred = (earliest_failed_ancestor_selection(candidates, trust)
                        or result.fault_root)
        except Exception as exc:
            new_pred = f"ERROR: {exc}"
        match = ("S3" if new_pred == GT_ROOT else "x")
        print(f"step {step}: active={active} old={OLD_PRED} new={new_pred} "
              f"candidate={candidates} GT={GT_ROOT} {'MATCH' if new_pred==GT_ROOT else ''}")


if __name__ == "__main__":
    main()
