import json
from types import SimpleNamespace

from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import NodeStatus
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient
from stateguard.runtime.episode_runner import EpisodeRunner


def _state(nodes):
    return SimpleNamespace(serialize=lambda: {"nodes": nodes})


def test_advance_baseline_state_marks_executed_and_is_idempotent():
    state = compile_from_spec({"nodes": [
        {"node_id": "S1", "description": "step 1", "dependencies": [],
         "expected_result": "x"},
    ]})
    EpisodeRunner._advance_baseline_state(state, "S1")
    assert state.get("S1").status == NodeStatus.EXECUTED
    EpisodeRunner._advance_baseline_state(state, "S1")
    assert state.get("S1").status == NodeStatus.EXECUTED
    EpisodeRunner._advance_baseline_state(state, "missing")
    assert state.get("S1").status == NodeStatus.EXECUTED


def test_executor_allows_executed_deps_when_verification_disabled():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        return {
            "subgoal_id": "S2", "intent": "click", "expected_effect": "visible",
            "action": {"type": "click", "x": 10, "y": 10}, "is_finish": False,
        }

    nodes = {
        "S1": {"status": "executed", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }
    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(100, 100), require_verified_deps=False)
    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))
    assert result.subgoal_id == "S2"
    assert calls[0] == 1


def test_frontier_allows_executed_deps_only_for_control_baseline():
    nodes = {
        "S1": {"status": "executed", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }
    baseline = MLLMExecutor(
        MockModelClient(lambda *_args: {}), "Do the task",
        require_verified_deps=False, guidance="frontier")
    guarded = MLLMExecutor(
        MockModelClient(lambda *_args: {}), "Do the task",
        require_verified_deps=True, guidance="frontier")

    assert baseline._frontier_from_serialized(nodes) == ["S1", "S2"]
    assert guarded._frontier_from_serialized(nodes) == ["S1"]


def test_frontier_guided_baseline_can_advance_to_executed_dependency_child():
    captured = {}

    def policy(messages, _images, _schema):
        captured.update(json.loads(messages[0]["content"]))
        return {
            "subgoal_id": "S2", "intent": "continue", "expected_effect": "visible",
            "action": {"type": "click", "x": 10, "y": 10}, "is_finish": False,
        }

    nodes = {
        "S1": {"status": "executed", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", bounds=ActionBounds(100, 100),
        require_verified_deps=False, guidance="frontier")

    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))

    assert result.subgoal_id == "S2"
    assert [item["node_id"] for item in captured["frontier"]] == ["S1", "S2"]
    assert "executed or verified" in captured["dependency_policy"]


def test_executor_still_blocks_pending_deps_when_verification_disabled():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        return {
            "subgoal_id": "S2", "intent": "click", "expected_effect": "visible",
            "action": {"type": "click", "x": 10, "y": 10}, "is_finish": False,
        }

    nodes = {
        "S1": {"status": "pending", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }
    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(100, 100), require_verified_deps=False)
    # S1 is still pending, so S2 stays blocked and the executor exhausts retries.
    try:
        executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))
    except ValueError as exc:
        assert "executor_parse_failed" in str(exc)
    else:
        raise AssertionError("expected blocked dependency to raise")


def test_executor_reconciles_when_ui_model_selects_direct_successor():
    def policy(_messages, _images, _schema):
        return {
            "subgoal_id": "S3", "intent": "continue in dialog",
            "expected_effect": "dialog changes",
            "action": {"type": "click", "x": 10, "y": 10},
            "subgoal_done": False, "is_finish": False,
        }

    nodes = {
        "S1": {"status": "verified", "dependencies": []},
        "S2": {"status": "executed", "dependencies": ["S1"]},
        "S3": {"status": "pending", "dependencies": ["S2"]},
    }
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", bounds=ActionBounds(100, 100),
        max_parse_retries=1, require_verified_deps=True, guidance="frontier")

    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))

    assert result.subgoal_id == "S2"
    assert result.action == {"type": "wait"}
    assert result.subgoal_done is True
    assert result.effect_observability == "none"


def test_guarded_executor_reconciles_repeated_premature_finish():
    prompts = []

    def policy(messages, _images, _schema):
        prompts.append(json.loads(messages[0]["content"]))
        return {
            "subgoal_id": "", "intent": "finish", "expected_effect": "done",
            "action": {}, "subgoal_done": True, "is_finish": True,
            "effect_observability": "none",
        }

    nodes = {
        "S1": {"status": "verified", "dependencies": [], "required": True},
        "S2": {"status": "executed", "dependencies": ["S1"], "required": True},
    }
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", max_parse_retries=3,
        require_verified_deps=True, guidance="frontier")

    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))

    assert len(prompts) == 2
    assert prompts[0]["finish_allowed"] is False
    assert prompts[0]["incomplete_required_nodes"] == ["S2"]
    assert result.subgoal_id == "S2"
    assert result.action == {"type": "wait"}
    assert result.subgoal_done is True
    assert executor.finish_reconciliation_count == 1


def test_guarded_executor_accepts_corrected_frontier_action_after_early_finish():
    calls = [0]

    def policy(_messages, _images, _schema):
        calls[0] += 1
        if calls[0] == 1:
            return {
                "subgoal_id": "", "intent": "finish", "expected_effect": "done",
                "action": {}, "subgoal_done": True, "is_finish": True,
            }
        return {
            "subgoal_id": "S2", "intent": "continue", "expected_effect": "visible",
            "action": {"type": "click", "x": 1, "y": 1},
            "subgoal_done": False, "is_finish": False,
        }

    nodes = {
        "S1": {"status": "verified", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", bounds=ActionBounds(10, 10),
        max_parse_retries=3, require_verified_deps=True, guidance="frontier")

    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))

    assert calls[0] == 2
    assert result.subgoal_id == "S2"
    assert result.action["type"] == "click"
    assert executor.finish_reconciliation_count == 0


def test_executor_only_control_keeps_model_finish_semantics():
    captured = {}

    def policy(messages, _images, _schema):
        captured.update(json.loads(messages[0]["content"]))
        return {
            "subgoal_id": "", "intent": "finish", "expected_effect": "done",
            "action": {}, "subgoal_done": True, "is_finish": True,
        }

    nodes = {"S1": {"status": "executed", "dependencies": [], "required": True}}
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task",
        require_verified_deps=False, guidance="frontier")

    result = executor.act(Observation(step=1, screenshot=b"png"), _state(nodes))

    assert captured["finish_allowed"] is True
    assert result.is_finish is True
    assert executor.finish_reconciliation_count == 0
