"""Causal fault localization (指引.txt §13). Rule-based Phase I.

Causal root = earliest task-state node whose expected condition is
contradicted/unsupported while its prerequisite dependencies are still
verified. Priority:
  1. candidate whose expected_result is directly contradicted by observation
  2. candidate whose own status is not VERIFIED (missing/unverified subgoal)
  3. the observed contradicted node itself
"""

from __future__ import annotations

from ..core.schema import FaultType, NodeStatus, TaskNode
from ..core.task_state import VerifiedTaskState
from ..core.dependency_graph import DependencyGraph
from ..interfaces.observation import Observation
from .parser import predicate_violated

_SELECTOR_VERBS = ("select", "open", "switch", "navigate", "push", "choose",
                   "paste", "upload", "download", "launch", "connect", "attach")


def causal_root(state: VerifiedTaskState, graph: DependencyGraph,
                contradicted: str, obs: Observation,
                check_result: str | None) -> tuple[str, str, float]:
    """Returns (root_id, fault_type, confidence)."""
    path = graph.ancestors(contradicted) + [contradicted]
    candidates = [m for m in path if _parents_verified(state, graph, m)] or [contradicted]

    for m in candidates:  # rule 1: direct contradiction, earliest first
        if predicate_violated(state.get(m).expected_result, obs.snapshot):
            return m, _classify(state, m, obs, check_result if m == contradicted else None), 1.0

    for m in candidates:  # rule 2: earliest non-verified node on the path
        if state.get(m).status != NodeStatus.VERIFIED:
            return m, _classify(state, m, obs, None), 0.7

    return contradicted, _classify(state, contradicted, obs, check_result), 0.5


def _parents_verified(state: VerifiedTaskState, graph: DependencyGraph, node: str) -> bool:
    return all(state.get(p).status == NodeStatus.VERIFIED for p in graph.parents(node))


def _classify(state: VerifiedTaskState, node_id: str, obs: Observation,
              check_result: str | None) -> str:
    node = state.get(node_id)
    status = node.status
    if status == NodeStatus.PENDING:
        return FaultType.MISSING_SUBGOAL.value
    if status in (NodeStatus.FAILED, NodeStatus.STALE):
        return FaultType.DEPENDENCY_VIOLATION.value
    if check_result == "missing":
        return FaultType.NOT_PERSISTED.value if _persistence(node) else FaultType.NO_EFFECT.value
    if check_result == "mismatch" or predicate_violated(node.expected_result, obs.snapshot):
        return FaultType.WRONG_TARGET.value if _is_selector(node) else FaultType.WRONG_VALUE.value
    if status == NodeStatus.EXECUTED:
        return FaultType.NOT_PERSISTED.value if _persistence(node) else FaultType.DEPENDENCY_VIOLATION.value
    if status == NodeStatus.ACTIVE:
        return FaultType.DEPENDENCY_VIOLATION.value
    return FaultType.WRONG_VALUE.value


def _persistence(node: TaskNode) -> bool:
    return bool(getattr(node, "verify_action", None))


def _is_selector(node: TaskNode) -> bool:
    text = f"{node.description} {node.expected_result}".lower()
    return any(v in text for v in _SELECTOR_VERBS)


def fault_type_for_injection(node_desc: str) -> str:
    """ponytail: generators label injected faults with the same heuristic the
    runtime uses, so offline gt and runtime predictions stay consistent."""
    return FaultType.WRONG_TARGET.value if any(
        v in node_desc.lower() for v in _SELECTOR_VERBS
    ) else FaultType.WRONG_VALUE.value
