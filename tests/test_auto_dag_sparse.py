"""Tests for Auto-DAG planning, executable frontier, subgoal_done, and sparse
verification (planning/phase-11)."""

from types import SimpleNamespace

from experiments.poc.faults import make_injector
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.schema import (ActionProposal, Evidence, GuardResult,
                                    NodeStatus, RepairRequest)
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds, parse_executor_output
from stateguard.guard.repair import build_repair_request, propagate_failure
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient
from stateguard.planning.parser import AutoDAGError, parse_auto_dag, validate_auto_dag
from stateguard.runtime.checkpoint_policy import (CheckpointPolicy,
                                                  NodeRisk, compute_node_risk)
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.runtime.history import ActionHistory


# ---------------------------------------------------------------------------
# Auto-DAG parser / validator
# ---------------------------------------------------------------------------

def test_auto_dag_parser_valid():
    nodes = parse_auto_dag({"nodes": [
        {"node_id": "S1", "description": "reach the settings page",
         "dependencies": [], "evidence_mode": "visual", "required": True},
        {"node_id": "S2", "description": "the setting is enabled",
         "dependencies": ["S1"], "evidence_mode": "persistence", "required": True},
    ]})
    report = validate_auto_dag(nodes)
    assert report["valid"] and report["node_count"] == 2 and report["edge_count"] == 1
    assert nodes[0]["expected_result_semantic"] == "reach the settings page"


def test_auto_dag_reject_cycle():
    nodes = parse_auto_dag({"nodes": [
        {"node_id": "S1", "description": "a", "dependencies": ["S2"]},
        {"node_id": "S2", "description": "b", "dependencies": ["S1"]},
    ]})
    try:
        validate_auto_dag(nodes)
    except AutoDAGError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("expected cycle rejection")


def test_auto_dag_reject_missing_dependency():
    nodes = parse_auto_dag({"nodes": [
        {"node_id": "S1", "description": "a", "dependencies": []},
        {"node_id": "S2", "description": "b", "dependencies": ["S9"]},
    ]})
    try:
        validate_auto_dag(nodes)
    except AutoDAGError as exc:
        assert "S9" in str(exc)
    else:
        raise AssertionError("expected missing-dependency rejection")


def test_auto_dag_no_hidden_runtime_fields():
    raw = {"nodes": [
        {"node_id": "S1", "description": "a", "dependencies": [],
         "fault_root": "S1", "evaluator": "gold", "expected_affected": ["S1"]},
        {"node_id": "S2", "description": "b", "dependencies": ["S1"]},
    ]}
    try:
        parse_auto_dag(raw)
    except AutoDAGError as exc:
        assert "disallowed" in str(exc).lower() or "fault_root" in str(exc)
    else:
        raise AssertionError("hidden runtime fields must be rejected")


def test_auto_dag_rejects_wrong_node_count():
    try:
        parse_auto_dag({"nodes": [
            {"node_id": "S1", "description": "only one node"},
        ]})
    except AutoDAGError as exc:
        assert "2-8" in str(exc)
    else:
        raise AssertionError("expected node-count rejection")


# ---------------------------------------------------------------------------
# Executable frontier
# ---------------------------------------------------------------------------

def test_frontier_only_unlocked_nodes():
    state = compile_from_spec({"nodes": [
        {"node_id": "S1", "description": "s1", "dependencies": [],
         "expected_result_semantic": "s1 achieved"},
        {"node_id": "S2", "description": "s2", "dependencies": ["S1"],
         "expected_result_semantic": "s2 achieved"},
        {"node_id": "S3", "description": "s3", "dependencies": ["S2"],
         "expected_result_semantic": "s3 achieved"},
    ]})
    graph = DependencyGraph.from_state(state)
    assert graph.executable_frontier(state) == ["S1"]
    state.mark_active("S1"); state.mark_executed("S1")
    state.mark_verified("S1", Evidence(1, "t", "ok", 0.9))
    assert graph.executable_frontier(state) == ["S2"]
    state.mark_active("S2"); state.mark_executed("S2")
    # executed but not verified -> still in frontier
    assert graph.executable_frontier(state) == ["S2"]


def test_executor_rejects_node_outside_frontier():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        node = "S2" if calls[0] == 1 else "S1"  # S2 blocked until S1 verified
        return {"subgoal_id": node, "intent": "act", "expected_effect": "visible",
                "action": {"type": "click", "x": 10, "y": 10},
                "subgoal_done": False, "is_finish": False}

    state = SimpleNamespace(serialize=lambda: {"nodes": {
        "S1": {"node_id": "S1", "description": "s1", "dependencies": [], "status": "pending"},
        "S2": {"node_id": "S2", "description": "s2", "dependencies": ["S1"], "status": "pending"},
    }})
    executor = MLLMExecutor(MockModelClient(policy), "task",
                            bounds=ActionBounds(100, 100), guidance="frontier")
    result = executor.act(Observation(step=1, screenshot=b"png"), state)
    assert result.subgoal_id == "S1"
    assert calls[0] == 2


# ---------------------------------------------------------------------------
# subgoal_done default
# ---------------------------------------------------------------------------

def test_subgoal_done_defaults_false():
    p = parse_executor_output({"subgoal_id": "S1", "intent": "i", "expected_effect": "e",
                               "action": {"type": "click", "x": 1, "y": 2},
                               "is_finish": False})
    assert p.subgoal_done is False
    p2 = parse_executor_output({"subgoal_id": "S1", "intent": "i", "expected_effect": "e",
                                "action": {"type": "click", "x": 1, "y": 2},
                                "subgoal_done": True, "is_finish": False})
    assert p2.subgoal_done is True


# ---------------------------------------------------------------------------
# Sparse verification scheduler
# ---------------------------------------------------------------------------

class CapturingExecutor:
    """Returns a scripted sequence of (subgoal_id, action, subgoal_done)."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.index = 0
        self.contexts = []

    def act(self, observation, task_state, repair_context=None):
        self.contexts.append(repair_context)
        if self.index >= len(self.actions):
            return ActionProposal("", {}, "finish", "", True, True)
        item = self.actions[self.index]
        node, action, done = item[:3]
        observability = item[3] if len(item) > 3 else "auto"
        self.index += 1
        return ActionProposal(
            node, action, node, "", done,
            effect_observability=observability)


class CapturingGuard:
    def __init__(self, verdict="verified", finish_approved=False, reject_reverify=None):
        self.calls = []
        self.verdict = verdict
        self.finish_approved = finish_approved
        self.reject_reverify = reject_reverify or ["S1"]

    def verify_transition(self, task_state, before, proposal, after,
                          checkpoint_kind="completion", candidate_nodes=None):
        self.calls.append(("transition", proposal.subgoal_id, proposal.subgoal_done,
                           checkpoint_kind))
        if self.verdict == "contradicted":
            return GuardResult(
                "contradicted", fault_root=proposal.subgoal_id, fault_type="no_effect",
                state_updates=[{"op": "fail", "node_id": proposal.subgoal_id}],
                repair=RepairRequest(fault_root=proposal.subgoal_id, error_type="no_effect",
                                     goal="repair", preserve_nodes=[],
                                     stale_nodes=[], reverify_nodes=self.reject_reverify))
        if self.verdict == "unknown":
            return GuardResult("unknown", state_updates=[], verification_target="target")
        return GuardResult(
            "verified",
            progress_updates=[{"node_id": proposal.subgoal_id, "status": "verified",
                               "evidence": "ok"}],
            state_updates=[{"op": "verify", "node_id": proposal.subgoal_id,
                            "evidence": {"step_id": 1, "source": "test",
                                         "description": "ok", "confidence": 0.9}}],
            approved=False)

    def verify_finish(self, task_state, observation):
        self.calls.append(("finish", None, None))
        if self.finish_approved:
            return GuardResult("verified", approved=True)
        return GuardResult(
            "contradicted", fault_root="S1", fault_type="premature_finish",
            repair=RepairRequest(fault_root="S1", error_type="premature_finish",
                                 goal="finish the task", preserve_nodes=[],
                                 stale_nodes=[], reverify_nodes=self.reject_reverify))


def _state(*nodes):
    return compile_from_spec({"nodes": [{"node_id": n, "description": n,
                                         "dependencies": deps,
                                         "expected_result_semantic": f"{n} achieved"}
                                        for n, deps in nodes]})


def _state_persist():
    return compile_from_spec({"nodes": [
        {"node_id": "S1", "description": "s1", "dependencies": [],
         "evidence_mode": "persistence", "expected_result_semantic": "s1 persisted"},
        {"node_id": "S2", "description": "s2", "dependencies": ["S1"],
         "evidence_mode": "visual", "expected_result_semantic": "s2 achieved"},
    ]})


def test_sparse_no_guard_on_normal_atomic_action():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)])
    guard_cap = CapturingGuard()
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=1, mode="stateguard",
                           verification_policy="sparse")
    runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
               {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert guard_cap.calls == []  # no checkpoint on a normal atomic action
    assert state.get("S1").status == NodeStatus.EXECUTED  # auto-advanced


def test_sparse_guard_on_subgoal_done():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, True)])
    guard_cap = CapturingGuard(verdict="verified")
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=2, mode="stateguard",
                           verification_policy="sparse")
    runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
               {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert any(c[0] == "transition" for c in guard_cap.calls)
    assert state.get("S1").status == NodeStatus.VERIFIED


def test_sparse_guard_on_finish():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([])  # immediate finish
    guard_cap = CapturingGuard(finish_approved=True)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=5, mode="stateguard",
                           verification_policy="sparse")
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert any(c[0] == "finish" for c in guard_cap.calls)
    assert result.status == "completed"
    assert "finish" in result.checkpoint_reasons


def test_guard_finish_transport_failure_is_recorded():
    class FailingGuard(CapturingGuard):
        def verify_finish(self, task_state, observation):
            raise RuntimeError("guard transport unavailable")

    runner = EpisodeRunner(
        CapturingExecutor([]), FailingGuard(), max_total_steps=2,
        mode="stateguard", verification_policy="sparse")
    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (10, 10)),
        _state(("S1", [])),
        {"initial_state": {}, "success_state": {}, "action_rules": []})

    assert result.status == "model_failed"
    assert result.error == "guard transport unavailable"


def test_guard_transition_transport_failure_is_recorded():
    class FailingGuard(CapturingGuard):
        def verify_transition(self, *args, **kwargs):
            raise RuntimeError("guard transport unavailable")

    runner = EpisodeRunner(
        CapturingExecutor([
            ("S1", {"type": "click", "x": 1, "y": 1}, True),
        ]),
        FailingGuard(), max_total_steps=2,
        mode="stateguard", verification_policy="sparse")
    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (10, 10)),
        _state(("S1", [])),
        {"initial_state": {}, "success_state": {}, "action_rules": []})

    assert result.status == "model_failed"
    assert result.error == "guard transport unavailable"


def test_sparse_guard_on_stagnation():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)] * 3)
    guard_cap = CapturingGuard(verdict="verified")
    policy = CheckpointPolicy(policy="sparse", repeated_action_threshold=3)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=6, mode="stateguard",
                           verification_policy="sparse", checkpoint_policy=policy)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert any(c[0] == "transition" for c in guard_cap.calls)
    assert "stagnation" in result.checkpoint_reasons


def test_sparse_stagnation_on_long_subgoal_wander():
    # varied actions on the same subgoal never match repeated-action detection,
    # but track_subgoal still fires a checkpoint after max_actions_per_subgoal.
    state = _state(("S1", []))
    varied = [("S1", {"type": "click", "x": i, "y": i + 1}, False) for i in range(1, 12)]
    exec_cap = CapturingExecutor(varied)
    guard_cap = CapturingGuard(verdict="verified")
    policy = CheckpointPolicy(policy="sparse", repeated_action_threshold=10,
                              same_subgoal_step_threshold=8)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=20, mode="stateguard",
                           verification_policy="sparse", checkpoint_policy=policy)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert any(c[0] == "transition" for c in guard_cap.calls)
    assert "stagnation" in result.checkpoint_reasons


def test_unknown_does_not_trigger_repair():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, True)])
    guard_cap = CapturingGuard(verdict="unknown", finish_approved=True)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=2, mode="stateguard",
                           verification_policy="sparse")
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert result.repair_cycle_count == 0
    assert result.contradiction_count == 0
    assert result.unknown_checkpoint_count == 1
    assert result.status != "verification_failed"
    assert state.get("S1").status == NodeStatus.EXECUTED  # unresolved, not failed


def test_unknown_does_not_immediately_requery():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([
        ("S1", {"type": "click", "x": 1, "y": 1}, True),   # checkpoint -> unknown
        ("S1", {"type": "click", "x": 2, "y": 2}, False),  # normal action, no requery
    ])
    guard_cap = CapturingGuard(verdict="unknown")
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=3, mode="stateguard",
                           verification_policy="sparse")
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    transitions = [c for c in guard_cap.calls if c[0] == "transition"]
    assert len(transitions) == 1  # only the subgoal_done checkpoint triggered a call
    assert result.unknown_checkpoint_count == 1


def test_repeated_unknown_unchanged_actions_converge_to_no_effect_repair():
    state = _state(("S1", []))
    state.get("S1").expected_result_semantic = "The requested menu is open and visible"
    actions = [
        ("S1", {"type": "click", "x": 10, "y": 10}, True, "visual"),
        ("S1", {"type": "click", "x": 30, "y": 25}, True, "visual"),
        ("S1", {"type": "click", "x": 55, "y": 40}, True, "visual"),
    ]
    history = ActionHistory()
    runner = EpisodeRunner(
        CapturingExecutor(actions), CapturingGuard(verdict="unknown"),
        max_total_steps=3, mode="stateguard", history=history,
        verification_policy="sparse", unchanged_observation_threshold=3)

    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {"done": True}, "action_rules": []})

    assert result.unknown_checkpoint_count == 3
    assert result.suspicious_checkpoint_count == 1
    assert result.contradiction_count == 1
    assert result.repair_cycle_count == 1
    assert result.repair_events[0]["error_type"] == "no_effect"
    assert state.get("S1").status == NodeStatus.FAILED
    assert history.blocked_actions()[0]["action"] == actions[-1][1]


def test_repair_stagnation_blocks_action_without_starting_nested_repair():
    class SequenceGuard(CapturingGuard):
        def __init__(self):
            super().__init__()
            self.verdicts = iter(["contradicted", "unknown", "unknown", "unknown"])

        def verify_transition(self, *args, **kwargs):
            self.verdict = next(self.verdicts)
            return super().verify_transition(*args, **kwargs)

    state = _state(("S1", []))
    state.get("S1").expected_result_semantic = "The requested menu is open and visible"
    action = {"type": "click", "x": 10, "y": 10}
    history = ActionHistory()
    runner = EpisodeRunner(
        CapturingExecutor([("S1", action, True, "visual")] * 4), SequenceGuard(),
        max_total_steps=4, mode="stateguard", history=history,
        verification_policy="sparse", unchanged_observation_threshold=3)

    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {"done": True}, "action_rules": []})

    assert result.repair_cycle_count == 1
    assert result.contradiction_count == 1
    assert not result.repair_budget_exhaustions
    assert history.blocked_actions()


def test_preparatory_action_stagnation_does_not_fail_the_subgoal():
    state = _state_persist()
    action = {"type": "click", "x": 10, "y": 10}
    history = ActionHistory()
    policy = CheckpointPolicy(
        policy="hybrid", high_risk_interval=1, checkpoint_cooldown=0)
    runner = EpisodeRunner(
        CapturingExecutor([("S1", action, False, "visual")] * 3),
        CapturingGuard(verdict="unknown"), max_total_steps=3,
        mode="stateguard", history=history, verification_policy="hybrid",
        checkpoint_policy=policy, unchanged_observation_threshold=3)

    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {"done": True}, "action_rules": []})

    assert result.repair_cycle_count == 0
    assert result.contradiction_count == 0
    assert history.blocked_actions()
    assert state.get("S1").status == NodeStatus.SUSPICIOUS


def test_descendant_reverification_does_not_consume_root_restore_budget():
    class SequenceGuard(CapturingGuard):
        def __init__(self):
            super().__init__(finish_approved=True, reject_reverify=["S1", "S2"])
            self.verdicts = iter(["contradicted", "verified", "verified"])

        def verify_transition(self, *args, **kwargs):
            self.verdict = next(self.verdicts)
            return super().verify_transition(*args, **kwargs)

    state = _state(("S1", []), ("S2", ["S1"]))
    actions = [
        ("S1", {"type": "click", "x": 10, "y": 10}, True),
        ("S1", {"type": "click", "x": 100, "y": 10}, True),
        ("S2", {"type": "click", "x": 100, "y": 100}, True),
    ]
    runner = EpisodeRunner(
        CapturingExecutor(actions), SequenceGuard(), max_total_steps=4,
        mode="stateguard", verification_policy="sparse",
        max_repair_actions_per_cycle=1)

    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (200, 200)), state,
        {"initial_state": {}, "success_state": {}, "action_rules": []})

    assert result.status == "completed"
    assert not result.repair_budget_exhaustions


def test_non_visual_actions_do_not_support_visual_no_effect_inference():
    state = _state(("S1", []))
    node = state.get("S1")
    node.expected_result_semantic = "The calendar layout is understood"
    cognitive_click = ActionProposal(
        "S1", {"type": "click", "x": 10, "y": 10},
        "inspect", "The calendar layout is understood")
    cognitive_mapping = ActionProposal(
        "S1", {"type": "click", "x": 20, "y": 20},
        "inspect", "The day-of-week mapping is established")
    visible_click = ActionProposal(
        "S1", {"type": "click", "x": 30, "y": 30},
        "open", "opaque model prose", effect_observability="visual")
    wait = ActionProposal("S1", {"type": "wait"}, "wait", "page loads")
    copy = ActionProposal(
        "S1", {"type": "hotkey", "keys": ["ctrl", "c"]},
        "copy", "value copied")
    structured = ActionProposal(
        "S1", {"type": "hotkey", "keys": ["enter"]},
        "commit", "record updates", effect_observability="structured")

    assert not EpisodeRunner._action_supports_no_effect(cognitive_click)
    assert not EpisodeRunner._action_supports_no_effect(cognitive_mapping)
    assert EpisodeRunner._action_supports_no_effect(visible_click)
    assert not EpisodeRunner._action_supports_no_effect(wait)
    assert not EpisodeRunner._action_supports_no_effect(copy)
    assert EpisodeRunner._action_supports_no_effect(structured)
    assert EpisodeRunner._observation_effect_unchanged(
        structured, Observation({"value": 1}), Observation({"value": 1}))


def test_nonvisual_unknown_requests_plan_revision_instead_of_repair():
    state = _state(("S1", []))
    actions = [
        ("S1", {"type": "click", "x": 10, "y": 10}, True, "none")
    ] * 6
    runner = EpisodeRunner(
        CapturingExecutor(actions), CapturingGuard(verdict="unknown"),
        max_total_steps=8, mode="stateguard", verification_policy="sparse",
        unchanged_observation_threshold=3)

    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {"done": True}, "action_rules": []})

    assert result.status == "plan_revision_required"
    assert result.plan_revision_count == 1
    assert result.repair_cycle_count == 0
    assert result.contradiction_count == 0


def test_contradiction_triggers_repair():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, True)])
    guard_cap = CapturingGuard(verdict="contradicted", finish_approved=True)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=2, mode="stateguard",
                           verification_policy="sparse")
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert result.repair_cycle_count == 1
    assert result.contradiction_count == 1
    assert state.get("S1").status == NodeStatus.FAILED


def test_repair_preserves_independent_verified_nodes():
    state = _state(("S1", []), ("S2", ["S1"]), ("S3", []))
    for nid in ("S1", "S3"):
        state.mark_active(nid); state.mark_executed(nid)
        state.mark_verified(nid, Evidence(1, "t", "ok", 0.9))
    state.mark_active("S2"); state.mark_executed("S2")
    graph = DependencyGraph.from_state(state)
    propagate_failure(state, graph, "S2")
    req = build_repair_request(state, graph, "S2", "no_effect", 0.8)
    assert set(req.preserve_nodes) == {"S1", "S3"}
    assert state.get("S2").status == NodeStatus.FAILED
    assert state.get("S1").status == NodeStatus.VERIFIED
    assert state.get("S3").status == NodeStatus.VERIFIED


def test_fault_exposure_does_not_trigger_guard():
    state = _state(("S1", []))
    spec = {"fault_id": "f1", "type": "wrong_target", "root_node": "S1",
            "inject": {"trigger": {"subgoal_id": "S1", "action_type": "click", "occurrence": 1},
                       "mutation": {"coordinate_offset": {"dx": 2, "dy": 0}}},
            "exposure": {"mode": "immediate"}}
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)])
    guard_cap = CapturingGuard()
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=1, mode="stateguard",
                           verification_policy="sparse")
    runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
               {"initial_state": {}, "success_state": {}, "action_rules": []},
               injector=make_injector(spec))
    assert guard_cap.calls == []  # fault exposure must NOT trigger a guard call


def test_finish_requires_all_required_nodes_verified():
    state = _state(("S1", []), ("S2", ["S1"]))
    exec_cap = CapturingExecutor([])  # immediate finish with incomplete state
    guard_cap = CapturingGuard(finish_approved=False)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=2, mode="stateguard",
                           verification_policy="sparse", max_repair_cycles_per_fault=5)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert any(c[0] == "finish" for c in guard_cap.calls)  # finish always verified
    # premature finish is rejected but does NOT consume the causal repair budget
    assert result.repair_cycle_count == 0
    assert result.premature_finish_count >= 1
    assert result.checkpoint_reasons.count("finish") >= 1

# ---------------------------------------------------------------------------
# NodeRisk + Hybrid verification
# ---------------------------------------------------------------------------

def test_node_risk_mapping():
    state = _state(("S1", []), ("S2", ["S1"]), ("S3", ["S2"]))
    graph = DependencyGraph.from_state(state)
    assert compute_node_risk(state.get("S1"), graph) == NodeRisk.HIGH   # 2 descendants
    assert compute_node_risk(state.get("S2"), graph) == NodeRisk.MEDIUM  # 1 descendant
    assert compute_node_risk(state.get("S3"), graph) == NodeRisk.LOW     # leaf
    pers = compile_from_spec({"nodes": [{"node_id": "S1", "description": "s",
                                         "dependencies": [], "evidence_mode": "persistence",
                                         "expected_result_semantic": "x"}]})
    assert compute_node_risk(pers.get("S1"), DependencyGraph.from_state(pers)) == NodeRisk.HIGH


def test_hybrid_causal_risk_checkpoint():
    # S1 persistence -> HIGH risk; after high_risk_interval actions a proactive
    # consistency checkpoint fires even though subgoal_done is never set.
    state = _state_persist()
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)] * 2)
    guard_cap = CapturingGuard(verdict="verified")
    policy = CheckpointPolicy(policy="hybrid", high_risk_interval=2, checkpoint_cooldown=0)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=3, mode="stateguard",
                           verification_policy="hybrid", checkpoint_policy=policy)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert "causal_risk" in result.checkpoint_reasons
    assert any(c[0] == "transition" for c in guard_cap.calls)


def test_hybrid_low_risk_no_proactive_checkpoint():
    state = _state(("S1", []))  # leaf, visual -> LOW
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)] * 2)
    guard_cap = CapturingGuard(verdict="verified", finish_approved=True)
    policy = CheckpointPolicy(policy="hybrid", high_risk_interval=2, checkpoint_cooldown=0)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=3, mode="stateguard",
                           verification_policy="hybrid", checkpoint_policy=policy)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    transitions = [c for c in guard_cap.calls if c[0] == "transition"]
    assert len(transitions) == 0
    assert "causal_risk" not in result.checkpoint_reasons


def test_hybrid_cooldown_blocks_immediate_recheck():
    state = _state_persist()
    graph = DependencyGraph.from_state(state)
    policy = CheckpointPolicy(policy="hybrid", high_risk_interval=1, checkpoint_cooldown=2)
    # distinct actions (>75px apart) so the repeated-action detector never fires
    p1 = ActionProposal("S1", {"type": "click", "x": 1, "y": 1}, "i", "e")
    p2 = ActionProposal("S1", {"type": "click", "x": 200, "y": 200}, "i", "e")
    p3 = ActionProposal("S1", {"type": "click", "x": 400, "y": 400}, "i", "e")
    d1 = policy.evaluate(p1, state, graph)
    assert d1.reason == "causal_risk"
    d2 = policy.evaluate(p2, state, graph)   # 1 step after the checkpoint -> blocked
    assert not d2.should_verify
    d3 = policy.evaluate(p3, state, graph)   # 2 steps after -> allowed
    assert d3.reason == "causal_risk"


def test_consistency_checkpoint_uses_consistency_kind():
    state = _state_persist()
    exec_cap = CapturingExecutor([("S1", {"type": "click", "x": 1, "y": 1}, False)] * 2)
    guard_cap = CapturingGuard(verdict="verified")
    policy = CheckpointPolicy(policy="hybrid", high_risk_interval=2, checkpoint_cooldown=0)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=3, mode="stateguard",
                           verification_policy="hybrid", checkpoint_policy=policy)
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state,
                        {"initial_state": {}, "success_state": {}, "action_rules": []})
    assert "consistency" in result.checkpoint_kinds


# ---------------------------------------------------------------------------
# certified_clean (phase-15)
# ---------------------------------------------------------------------------

def test_clean_episode_sets_certified_clean():
    state = _state(("S1", []))
    exec_cap = CapturingExecutor([])  # immediate finish -> rejected -> intervention
    guard_cap = CapturingGuard(finish_approved=False)
    runner = EpisodeRunner(exec_cap, guard_cap, max_total_steps=2, mode="stateguard",
                           verification_policy="sparse", max_repair_cycles_per_fault=5)
    task = {"initial_state": {}, "success_state": {}, "action_rules": [],
            "certified_clean": True}
    result = runner.run(OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state, task)
    assert result.certified_clean is True
    assert result.guard_intervention_count > 0
    assert result.false_intervention_episode is False




# ---------------------------------------------------------------------------
# Consistency checkpoint fail-open on active node (phase-6)
# ---------------------------------------------------------------------------

def test_consistency_checkpoint_active_node_fail_open():
    from stateguard.guard.state_guard import StateGuard

    class FakeBackend:
        def verify(self, *a, **k):
            return GuardResult("contradicted", fault_root="S1", fault_type="no_effect",
                               progress_updates=[], verification_target=None)

    state = _state(("S1", []))
    guard = StateGuard(FakeBackend())
    before = Observation(step=1, screenshot=b"x")
    after = Observation(step=2, screenshot=b"y")
    proposal = ActionProposal("S1", {"type": "click", "x": 1, "y": 1}, "i", "e")
    # consistency checkpoint on the in-progress active node -> fail-open (unknown)
    r = guard.verify_transition(state, before, proposal, after,
                                checkpoint_kind="consistency")
    assert r.judgement == "unknown"
    assert r.repair is None
    # completion checkpoint -> real contradiction -> repair
    r2 = guard.verify_transition(state, before, proposal, after,
                                 checkpoint_kind="completion")
    assert r2.judgement == "contradicted"
    assert r2.repair is not None
