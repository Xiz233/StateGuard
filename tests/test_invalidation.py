"""Milestone 3: deterministic failure propagation (指引.txt §12/29):
root FAILED, descendants STALE, independent VERIFIED preserved."""

from stateguard.core.schema import NodeStatus, TaskNode
from stateguard.core.task_state import VerifiedTaskState
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.evidence import make_evidence
from stateguard.guard.repair import propagate_failure


def build():
    # S1 -> S2, S3 ; S2 -> S4  (S3 independent branch)
    nodes = {
        "S1": TaskNode(node_id="S1", description="1", expected_result="r1"),
        "S2": TaskNode(node_id="S2", description="2", dependencies=["S1"],
                       expected_result="r2"),
        "S3": TaskNode(node_id="S3", description="3", dependencies=["S1"],
                       expected_result="r3"),
        "S4": TaskNode(node_id="S4", description="4", dependencies=["S2"],
                       expected_result="r4"),
    }
    state = VerifiedTaskState(nodes)
    for nid in nodes:
        state.mark_active(nid)
        state.mark_executed(nid)
        state.mark_verified(nid, make_evidence(1, f"{nid} ok", 0.9))
    return state, DependencyGraph.from_state(state)


def test_root_failed_descendants_stale():
    state, graph = build()
    stale = propagate_failure(state, graph, "S2")
    assert state.get("S2").status == NodeStatus.FAILED
    assert state.get("S4").status == NodeStatus.STALE
    assert stale == ["S4"]


def test_independent_branch_preserved():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    assert state.get("S3").status == NodeStatus.VERIFIED  # unaffected
    assert state.get("S1").status == NodeStatus.VERIFIED  # ancestor preserved


def test_failure_on_root_stales_whole_subgraph():
    state, graph = build()
    propagate_failure(state, graph, "S1")
    assert all(state.get(nid).status == NodeStatus.STALE
               for nid in ("S2", "S3", "S4"))
    assert state.get("S1").status == NodeStatus.FAILED


def test_pending_descendants_not_staled():
    state, graph = build()
    state.get("S4").status = NodeStatus.PENDING  # not yet started
    propagate_failure(state, graph, "S2")
    assert state.get("S4").status == NodeStatus.PENDING  # §12: no flip


def test_verified_only_with_stale_evidence_is_invalidated_not_failed():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    # downstream was correct itself; its trust is gone, not its execution
    assert state.get("S4").status == NodeStatus.STALE
    assert state.get("S4").evidence  # evidence kept (node itself not wrong)


def test_stale_reactivation_legal():
    state, graph = build()
    propagate_failure(state, graph, "S2")
    state.mark_active("S2")
    state.mark_executed("S2")
    state.mark_verified("S2", make_evidence(2, "redone", 0.9))
    assert state.get("S2").status == NodeStatus.VERIFIED
