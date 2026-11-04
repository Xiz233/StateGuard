"""Milestone 1: schema, status transitions, evidence requirement,
FINISH rule, serialization (指引.txt §29)."""

import pytest

from stateguard.core.schema import NodeStatus, Evidence, TaskNode
from stateguard.core.task_state import VerifiedTaskState, IllegalTransitionError
from stateguard.core.evidence import make_evidence


def make_state():
    nodes = {
        "S1": TaskNode(node_id="S1", description="a", dependencies=[],
                       expected_result="x"),
        "S2": TaskNode(node_id="S2", description="b", dependencies=["S1"],
                       expected_result="y"),
    }
    return VerifiedTaskState(nodes)


def test_legal_transitions_full_chain():
    st = make_state()
    st.mark_active("S1")
    st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "ok", 0.9))
    assert st.get("S1").status == NodeStatus.VERIFIED


def test_illegal_transitions_raise():
    st = make_state()
    with pytest.raises(IllegalTransitionError):
        st.mark_verified("S1", make_evidence(1, "ok", 0.9))  # PENDING -> VERIFIED
    with pytest.raises(IllegalTransitionError):
        st.mark_failed("S1")  # PENDING -> FAILED
    st.mark_active("S1")
    with pytest.raises(IllegalTransitionError):
        st.mark_active("S1")  # ACTIVE -> ACTIVE


def test_stale_from_active_and_executed_and_verified():
    # §12: ACTIVE / EXECUTED / VERIFIED descendants all go STALE
    st = make_state()
    st.mark_active("S1")
    st.mark_stale(["S1"])
    assert st.get("S1").status == NodeStatus.STALE
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_stale(["S1"])
    assert st.get("S1").status == NodeStatus.STALE
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "ok", 0.9))
    st.mark_stale(["S1"])
    assert st.get("S1").status == NodeStatus.STALE


def test_verified_requires_evidence():
    st = make_state()
    st.mark_active("S1")
    st.mark_executed("S1")
    with pytest.raises(ValueError):
        st.mark_verified("S1", [])  # forbidden: VERIFIED with no evidence


def test_finish_rule():
    st = make_state()
    assert not st.can_finish()
    for nid in ("S1", "S2"):
        st.mark_active(nid)
        st.mark_executed(nid)
        st.mark_verified(nid, make_evidence(1, "ok", 0.9))
    assert st.can_finish()
    assert st.incomplete_required_nodes() == []


def test_finish_rule_ignores_non_required():
    nodes = {"S1": TaskNode(node_id="S1", description="a", expected_result="x"),
             "S2": TaskNode(node_id="S2", description="b", dependencies=["S1"],
                            expected_result="y", required=False)}
    st = VerifiedTaskState(nodes)
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "ok", 0.9))
    assert st.can_finish()  # S2 optional


def test_verified_nodes_ordering():
    st = make_state()
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "ok", 0.9))
    assert st.verified_nodes() == ["S1"]


def test_serialization_roundtrip():
    st = make_state()
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "ok", 0.9, "obs@1"))
    st.mark_active("S2"); st.mark_executed("S2")
    st.mark_verified("S2", make_evidence(2, "ok2", 0.8, "obs@2"))
    data = st.serialize()
    st2 = VerifiedTaskState.deserialize(data)
    assert st2.serialize() == st.serialize()
    assert st2.get("S1").evidence[0].description == "ok"


def test_deserialize_rejects_verified_without_evidence():
    data = {
        "nodes": {"S1": {"node_id": "S1", "description": "a", "dependencies": [],
                         "expected_result": "x", "status": "verified",
                         "evidence": [], "required": True}}
    }
    with pytest.raises(ValueError):
        VerifiedTaskState.deserialize(data)


def test_mark_verified_replaces_evidence():
    st = make_state()
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(1, "first", 0.9))
    st.mark_failed("S1")
    st.mark_active("S1"); st.mark_executed("S1")
    st.mark_verified("S1", make_evidence(2, "second", 0.9))
    assert st.get("S1").evidence[0].description == "second"


def test_guard_updates_are_atomic_when_a_later_transition_is_invalid():
    st = make_state()
    before = st.serialize()

    with pytest.raises(IllegalTransitionError):
        st.apply([
            {"op": "active", "node_id": "S1"},
            {"op": "verify", "node_id": "S2", "evidence": {
                "step_id": 1, "source": "test", "description": "invalid",
                "confidence": 1.0,
            }},
        ])

    assert st.serialize() == before
