from types import SimpleNamespace

from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.schema import ActionProposal, Evidence, GuardResult, NodeStatus
from stateguard.guard.localization import (
    candidate_root_generation,
    earliest_failed_ancestor_selection,
)
from stateguard.guard.state_guard import StateGuard
from stateguard.guard.backends.mllm_backend import MLLMBackend
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient
from stateguard.runtime.repair_loop import RepairBudget
from stateguard.trace import TraceCollector, TraceStorage, causal_trace_window


def _state():
    return compile_from_spec({"nodes": [
        {"node_id": "S1", "description": "open settings", "dependencies": [],
         "expected_result_semantic": "settings are open"},
        {"node_id": "S2", "description": "enable option", "dependencies": ["S1"],
         "expected_result_semantic": "option is enabled"},
        {"node_id": "S3", "description": "save option", "dependencies": ["S2"],
         "expected_result_semantic": "option is saved"},
    ]})


def _verify(state, node_id, step=1):
    state.mark_active(node_id)
    state.mark_executed(node_id)
    state.mark_verified(node_id, Evidence(step, "test", "visible", 0.9))


def test_trace_records_every_action():
    state = _state()
    storage = TraceStorage(max_entries=200)
    collector = TraceCollector(storage)
    proposal = ActionProposal("S1", {"type": "click", "x": 5, "y": 8},
                              "open settings", "settings visible",
                              effect_observability="visual")
    before = Observation(step=0, snapshot={"page": "desktop"})
    after = Observation(step=1, snapshot={"page": "settings"})
    collector.record_step(1, state, proposal=proposal, observation_before=before)
    collector.record_step(1, state, observation_after=after,
                          checkpoint_reason="subgoal_done",
                          checkpoint_kind="completion")
    assert len(storage.entries) == 1
    assert storage.entries[0].action["type"] == "click"
    assert storage.entries[0].effect_observability == "visual"


def test_trace_records_executed_action_after_fault_mutation():
    state = _state()
    collector = TraceCollector()
    proposal = ActionProposal("S1", {"type": "click", "x": 5, "y": 8},
                              "open settings", "settings visible")
    collector.record_step(
        1, state, proposal=proposal,
        executed_action={"type": "click", "x": 5, "y": 208},
        observation_before=Observation(step=0))
    entry = collector.record_step(
        1, state, observation_after=Observation(step=1))
    assert entry.action == {"type": "click", "x": 5, "y": 208}
    assert entry.proposed_action == {"type": "click", "x": 5, "y": 8}


def test_candidate_diagnosis_receives_proposed_and_executed_actions():
    captured = {}

    def policy(messages, images, schema):
        captured.update(__import__("json").loads(messages[0]["content"]))
        return {"trust_judgements": {"S1": "NO"}}

    backend = MLLMBackend(MockModelClient(policy))
    proposal = ActionProposal("S1", {"type": "click", "x": 5, "y": 8},
                              "open settings", "settings visible")
    trace = [{
        "step_id": 1,
        "active_node_id": "S1",
        "proposed_action": {"type": "click", "x": 5, "y": 8},
        "action": {"type": "click", "x": 5, "y": 8},
    }]

    result = backend.diagnose_candidates(
        _state(), Observation(step=0), proposal, Observation(step=1), ["S1"], trace
    )

    assert result == {"S1": "NO"}
    assert captured["causal_trace_window"][0]["proposed_action"] == (
        captured["causal_trace_window"][0]["action"])
    assert "later successful retry does not erase" in captured["instruction"]


def test_execution_divergence_is_deterministic_causal_evidence():
    def unexpected_model_call(messages, images, schema):
        raise AssertionError("structured divergence should bypass the model")

    backend = MLLMBackend(MockModelClient(unexpected_model_call))
    proposal = ActionProposal("S2", {"type": "click"}, "open", "visible")
    trace = [{
        "step_id": 1,
        "active_node_id": "S1",
        "proposed_action": {"type": "click", "x": 5, "y": 8},
        "action": {"type": "click", "x": 5, "y": 208},
    }]

    assert backend.diagnose_candidates(
        _state(), Observation(step=0), proposal, Observation(step=1),
        ["S1", "S2"], trace
    ) == {"S1": "NO", "S2": "YES"}


def test_trace_contains_state_transition():
    state = _state()
    collector = TraceCollector()
    proposal = ActionProposal("S1", {"type": "click"}, "open", "visible")
    collector.record_step(1, state, proposal=proposal,
                          observation_before=Observation(step=0))
    _verify(state, "S1")
    entry = collector.record_step(1, state, observation_after=Observation(step=1))
    assert entry.state_before["nodes"]["S1"]["status"] == "pending"
    assert entry.state_after["nodes"]["S1"]["status"] == "verified"
    assert entry.trust_snapshot["S1"] == 1.0


def test_trace_window_selection():
    state = _state()
    collector = TraceCollector()
    for step, node in enumerate(("S1", "S2", "S3"), 1):
        proposal = ActionProposal(node, {"type": "click"}, node, "visible")
        collector.record_step(step, state, proposal=proposal,
                              observation_before=Observation(step=step - 1))
        collector.record_step(step, state, observation_after=Observation(step=step))
    window = causal_trace_window(collector.storage.entries, "S2", ["S1"])
    assert [entry.active_node_id for entry in window] == ["S1", "S2"]


def test_verified_to_suspicious():
    state = _state()
    _verify(state, "S1")
    state.mark_suspicious("S1", "weak contradiction", 2)
    assert state.get("S1").status == NodeStatus.SUSPICIOUS
    assert state.get("S1").trust_score == 0.8
    assert state.get("S1").suspicious_since_step == 2


class _ContradictingBackend:
    def verify(self, task_state, before, proposal, after, **kwargs):
        return GuardResult("contradicted", fault_root="S1", fault_type="wrong_value",
                           reason="weak visual mismatch")


def test_suspicious_requires_confirmation():
    state = _state()
    _verify(state, "S1")
    proposal = ActionProposal("S2", {"type": "click"}, "enable", "enabled")
    guard = StateGuard(_ContradictingBackend())
    weak = guard.verify_transition(
        state, Observation(step=1), proposal, Observation(step=2),
        checkpoint_kind="consistency", candidate_nodes=["S1", "S2"])
    assert weak.judgement == "unknown"
    assert weak.repair is None
    state.apply(weak.state_updates)
    assert state.get("S1").status == NodeStatus.SUSPICIOUS

    confirmed = guard.verify_transition(
        state, Observation(step=2), proposal, Observation(step=3),
        checkpoint_kind="completion", candidate_nodes=["S1", "S2"])
    assert confirmed.judgement == "contradicted"
    assert confirmed.repair.fault_root == "S1"


def test_suspicious_not_immediate_repair():
    state = _state()
    _verify(state, "S1")
    guard = StateGuard(_ContradictingBackend())
    result = guard.verify_transition(
        state, Observation(step=1),
        ActionProposal("S2", {"type": "click"}, "enable", "enabled"),
        Observation(step=2), checkpoint_kind="consistency")
    assert result.repair is None
    assert not result.requires_repair


def test_candidate_root_generation():
    graph = DependencyGraph.from_state(_state())
    assert candidate_root_generation(graph, "S3") == ["S1", "S2", "S3"]


def test_earliest_failed_ancestor_selection():
    verdicts = {"S1": "YES", "S2": "NO", "S3": "NO"}
    assert earliest_failed_ancestor_selection(["S1", "S2", "S3"], verdicts) == "S2"


def test_downstream_failure_not_root():
    verdicts = {"S1": "NO", "S2": "NO", "S3": "NO"}
    assert earliest_failed_ancestor_selection(["S1", "S2", "S3"], verdicts) == "S1"


def test_repair_budget_logging():
    budget = RepairBudget(max_cycles_per_fault=1, max_actions_per_cycle=2)
    assert budget.record_cycle("S1")
    assert budget.record_action("S1", 1)
    assert budget.record_action("S1", 1)
    assert not budget.record_action("S1", 1)
    assert not budget.record_cycle("S1")


def test_restore_then_revalidate_and_keep_valid_descendants():
    state = _state()
    _verify(state, "S1")
    _verify(state, "S2", 2)
    graph = DependencyGraph.from_state(state)
    assert state.get("S1").status == NodeStatus.VERIFIED
    assert graph.affected_set("S2") == ["S2", "S3"]
    assert "S1" not in graph.affected_set("S2")
