"""Milestone 4: RepairRequest scope (指引.txt §15/29): only affected nodes
are reactivated; independent verified nodes are preserved; affected set is
computed by deterministic graph code."""

import pytest

from stateguard.core.schema import NodeStatus, TaskNode, RepairRequest
from stateguard.core.task_state import VerifiedTaskState
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.evidence import make_evidence
from stateguard.guard.repair import propagate_failure, build_repair_request

# S1 -> S2 -> S3 -> S4 (linear), plus independent S5 -> S6
SPEC = {
    "nodes": [
        {"node_id": "S1", "description": "a", "dependencies": [],
         "expected_result": "r1"},
        {"node_id": "S2", "description": "b", "dependencies": ["S1"],
         "expected_result": "r2"},
        {"node_id": "S3", "description": "c", "dependencies": ["S2"],
         "expected_result": "r3"},
        {"node_id": "S4", "description": "d", "dependencies": ["S3"],
         "expected_result": "r4"},
        {"node_id": "S5", "description": "e", "dependencies": [],
         "expected_result": "r5"},
        {"node_id": "S6", "description": "f", "dependencies": ["S5"],
         "expected_result": "r6"},
    ]
}


def build():
    state = VerifiedTaskState(
        {n["node_id"]: TaskNode(**n) for n in SPEC["nodes"]})
    for nid in ["S1", "S2", "S3", "S4", "S5", "S6"]:
        state.mark_active(nid)
        state.mark_executed(nid)
        state.mark_verified(nid, make_evidence(1, "ok", 0.9))
    return state, DependencyGraph.from_state(state)


def test_repair_scope_is_minimal():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    repair = build_repair_request(state, graph, "S2", "wrong_target", 1.0)
    assert repair.reverify_nodes == ["S2", "S3", "S4"]  # affected only
    assert repair.preserve_nodes == ["S1", "S5", "S6"]  # verified & independent
    assert repair.stale_nodes == ["S3", "S4"]
    assert repair.fault_root == "S2"
    assert repair.error_type == "wrong_target"
    assert "S2" in repair.goal


def test_repair_request_fields():
    repair = RepairRequest(fault_root="S3", error_type="wrong_target",
                           goal="g", preserve_nodes=["S1", "S2"],
                           stale_nodes=["S4", "S5"],
                           reverify_nodes=["S3", "S4", "S5"],
                           confidence=0.9)
    d = repair.to_dict()
    assert d["fault_root"] == "S3"
    assert RepairRequest.from_dict(d) == repair


def test_repair_request_retargets_replaced_nodes_and_filters_removed_nodes():
    repair = RepairRequest(
        fault_root="S1R", error_type="no_effect", goal="restore",
        preserve_nodes=["P", "removed"], stale_nodes=["S1R", "removed"],
        reverify_nodes=["S1R", "D", "removed"], confidence=0.9,
        repair_cycle_id=2)

    mapped = repair.remap_nodes(
        {"S1R": "S1R-P", "removed": "replacement"},
        {"P", "S1R-P", "D"})

    assert mapped.fault_root == "S1R-P"
    assert mapped.preserve_nodes == ["P"]
    assert mapped.stale_nodes == ["S1R-P"]
    assert mapped.reverify_nodes == ["S1R-P", "D"]
    assert mapped.repair_cycle_id == 2
    assert repair.fault_root == "S1R"


def test_repair_request_rejects_a_root_without_live_replacement():
    repair = RepairRequest("missing", "no_effect", "restore")
    with pytest.raises(ValueError, match="no live replacement"):
        repair.remap_nodes({}, {"S1"})


def test_repair_never_touches_unrelated_branch():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    repair = build_repair_request(state, graph, "S2", "wrong_value", 1.0)
    assert "S5" not in repair.reverify_nodes
    assert "S6" not in repair.reverify_nodes


def test_repeated_failure_propagation_is_idempotent_for_failed_root():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    assert state.get("S2").status == NodeStatus.FAILED
    assert propagate_failure(state, graph, "S2") == []
    assert state.get("S2").status == NodeStatus.FAILED


def test_pending_descendants_remain_normal_future_work_after_repair():
    state = VerifiedTaskState(
        {n["node_id"]: TaskNode(**n) for n in SPEC["nodes"]})
    for nid in ("S1", "S2"):
        state.mark_active(nid)
        state.mark_executed(nid)
    graph = DependencyGraph.from_state(state)

    propagate_failure(state, graph, "S2")
    repair = build_repair_request(state, graph, "S2", "no_effect", 0.9)

    assert repair.reverify_nodes == ["S2"]
    assert "S3" not in repair.reverify_nodes
    assert state.get("S3").status == NodeStatus.PENDING
