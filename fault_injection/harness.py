"""Offline episode harness: compile -> execute -> verify -> localize ->
repair -> reverify, logging per §28 and collecting per-episode metrics.

Runtime components never see ground truth; only this offline harness does
(指引.txt §22: runtime/ vs offline_labeling/ separation).
"""

from __future__ import annotations

from copy import deepcopy

from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.guard.state_guard import StateGuard
from replay.mock_environment import MockEnvironment
from examples.synthetic_tasks.spec_executor import SpecExecutor
from eval.logging_utils import EpisodeLogger


def run_episode(spec: dict, name: str, hints: dict | None = None,
                fixes: dict | None = None, gt: dict | None = None,
                run_dir: str | None = None, max_steps: int = 200) -> dict:
    """Run the §18 runtime loop end-to-end; return per-episode metrics."""
    env = MockEnvironment(spec)
    state = compile_from_spec(spec)
    executor = SpecExecutor(spec, hints=hints)
    guard = StateGuard()
    logger = EpisodeLogger(run_dir, name) if run_dir else None

    obs = env.reset()
    if logger:
        logger.log_task(spec, state)

    repair_context = None
    fixes_applied = False
    step = 0
    contradictions = 0
    repair_actions = 0
    verified_before: list[str] = []
    first_repair = None
    timed_out = False

    while step < max_steps:
        step += 1
        proposal = executor.act(obs, state, repair_context)
        if proposal is None:
            break

        state_before = state.serialize()
        if proposal.is_finish:
            result = guard.verify_finish(state, obs)
            before = after = obs
        else:
            before = obs
            after = env.step(proposal.action)
            result = guard.verify_transition(state, before, proposal, after)
            obs = after

        if logger:
            logger.log_step(step, proposal, state_before, before, after,
                            result, result.state_updates)
            logger.log_guard_event(step, result)

        if result.judgement == "contradicted":
            contradictions += 1
            if first_repair is None:
                first_repair = result.repair
                verified_before = state.verified_nodes()
                if logger:
                    logger.log_repair(step, result.repair)
            if not fixes_applied:
                for action_name, effect in (fixes or {}).get("effects", {}).items():
                    env.fix_action(action_name, effect)
                if fixes:
                    executor.fix(fixes)
                fixes_applied = True
            repair_context = result.repair
        else:
            if repair_context is not None \
                    and all(nid in state.verified_nodes()
                            for nid in repair_context.reverify_nodes):
                repair_context = None
            elif repair_context is not None:
                repair_actions += 1

        state.apply(result.state_updates)

        if result.approved:
            break
    else:
        timed_out = True

    return _episode_metrics(name, spec, state, gt, contradictions, first_repair,
                            verified_before, repair_actions, step, timed_out,
                            logger)


def _episode_metrics(name, spec, state, gt, contradictions, first_repair,
                     verified_before, repair_actions, steps, timed_out, logger):
    affected = gt["affected_nodes"] if gt else []
    predicted_affected = []
    root_correct = None
    if gt is not None and first_repair is not None:
        predicted_affected = DependencyGraph.from_spec(spec["nodes"]).affected_set(
            first_repair.fault_root)
        root_correct = first_repair.fault_root == gt["fault_root"]

    final_verified = set(state.verified_nodes())
    preserved = len([n for n in verified_before
                     if n not in affected and n in final_verified])
    preservation = preserved / len(verified_before) if verified_before else 1.0

    metrics = {
        "episode": name,
        "contradictions": contradictions,
        "timed_out": timed_out,
        "recovered": state.can_finish() and not timed_out,
        "steps": steps,
        "predicted_root": first_repair.fault_root if first_repair else None,
        "predicted_fault_type": first_repair.error_type if first_repair else None,
        "root_correct": root_correct,
        "predicted_affected": predicted_affected,
        "gt_affected": affected,
        "reactivated": len(first_repair.reverify_nodes) if first_repair else 0,
        "repair_actions": repair_actions,
        "verified_before_failure": len(verified_before),
        "preserved_nodes": preserved,
        "progress_preservation_rate": preservation,
    }
    if logger:
        logger.finish(state, metrics)
    return metrics
