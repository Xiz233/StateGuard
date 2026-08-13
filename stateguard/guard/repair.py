"""Deterministic failure propagation + minimal repair request
(指引.txt §12/15). Only fault_root is a judgement; the affected set comes
from graph.descendants()."""

from __future__ import annotations

from ..core.schema import NodeStatus, RepairRequest
from ..core.task_state import VerifiedTaskState
from ..core.dependency_graph import DependencyGraph


def propagate_failure(state: VerifiedTaskState, graph: DependencyGraph,
                      fault_root: str) -> list[str]:
    """root -> FAILED; VERIFIED/EXECUTED/ACTIVE descendants -> STALE.
    Returns the newly-stale node ids.
    ponytail: a PENDING root (missing subgoal, never executed) has nothing
    to fail, so it stays PENDING and is handled by the repair loop."""
    if state.get(fault_root).status != NodeStatus.PENDING:
        state.mark_failed(fault_root)
    stale: list[str] = []
    for d in graph.descendants(fault_root):
        if state.get(d).status in (NodeStatus.VERIFIED, NodeStatus.EXECUTED,
                                   NodeStatus.ACTIVE):
            stale.append(d)
    state.mark_stale(stale)
    return stale


def build_repair_request(state: VerifiedTaskState, graph: DependencyGraph,
                         fault_root: str, error_type: str,
                         confidence: float) -> RepairRequest:
    """Repair target, preserved progress, states needing re-verification.
    Never regenerates the whole plan (指引.txt §15)."""
    affected = set(graph.affected_set(fault_root))
    verified = set(state.verified_nodes())
    preserve = sorted(nid for nid in verified if nid not in affected)
    stale = sorted(
        nid for nid in affected if state.get(nid).status == NodeStatus.STALE
    )
    reverify = graph.affected_set(fault_root)
    root = state.get(fault_root)
    goal = (
        f"Restore {root.description} without repeating {preserve or 'anything else'}; "
        f"then re-verify {reverify}."
    )
    return RepairRequest(
        fault_root=fault_root,
        error_type=error_type,
        goal=goal,
        preserve_nodes=preserve,
        stale_nodes=stale,
        reverify_nodes=reverify,
        confidence=confidence,
    )
