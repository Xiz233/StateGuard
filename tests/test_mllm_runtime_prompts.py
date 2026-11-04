import json
from types import SimpleNamespace

from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds
from stateguard.guard.backends.mllm_backend import MLLMBackend
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient


class State:
    def serialize(self):
        return {"nodes": {"S1": {"status": "pending"}}}

    def __contains__(self, node_id):
        return node_id == "S1"


def test_executor_prompt_defines_action_contract_and_correction_context():
    calls = []

    def policy(messages, images, schema):
        calls.append(messages)
        if len(calls) == 1:
            return {"bad": True}
        return {
            "subgoal_id": "S1", "intent": "click", "expected_effect": "menu opens",
            "action": {"type": "click", "x": 12, "y": 34}, "is_finish": False,
        }

    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(1920, 1080))
    result = executor.act(Observation(step=1, screenshot=b"png"), State())

    prompt = json.loads(calls[0][0]["content"])
    assert "subgoal_id" in prompt["output_contract"]
    assert '"type":"drag"' in prompt["output_contract"]
    assert "immediate visible effect" in prompt["output_contract"]
    assert "do not repeat" in prompt["output_contract"]
    assert "NEVER presses Enter" in prompt["output_contract"]
    assert "effect_observability" in prompt["output_contract"]
    assert '"clicks":1-3' in prompt["output_contract"]
    assert '"keys":["enter"]' in prompt["output_contract"]
    assert prompt["screen_bounds"] == {"width": 1920, "height": 1080}
    assert calls[1][-2]["role"] == "assistant"
    assert result.action == {"type": "click", "x": 12, "y": 34}


def test_guard_prompt_omits_screenshot_bytes_and_normalizes_visual_evidence():
    captured = {}

    def policy(messages, images, schema):
        captured["prompt"] = messages[0]["content"]
        captured["images"] = images
        return {
            "judgement": "verified",
            "progress_updates": [{
                "node_id": "S1", "status": "verified",
                "visual_evidence": ["menu is open", "Settings is visible"],
            }],
            "fault_root": None, "fault_type": None, "verification_target": None,
            "reason": "visible",
        }

    before = Observation(step=1, screenshot=b"BEFORE_BYTES")
    after = Observation(step=2, screenshot=b"AFTER_BYTES")
    proposal = SimpleNamespace(to_dict=lambda: {}, subgoal_id="S1")
    state = compile_from_spec({"nodes": [
        {
            "node_id": "S1", "description": "open the menu", "dependencies": [],
            "expected_result": "menu is open",
        },
        {
            "node_id": "S2", "description": "open the dialog",
            "dependencies": ["S1"], "expected_result": "dialog is open",
        },
    ]})
    result = MLLMBackend(MockModelClient(policy)).verify(
        state, before, proposal, after)

    assert "BEFORE_BYTES" not in captured["prompt"]
    assert "AFTER_BYTES" not in captured["prompt"]
    assert "partial progress" in captured["prompt"]
    payload = json.loads(captured["prompt"])
    assert payload["direct_successor_states"][0]["node_id"] == "S2"
    assert "does not need to remain visible" in payload["transient_state_policy"]
    assert captured["images"] == [b"BEFORE_BYTES", b"AFTER_BYTES"]
    assert result.progress_updates[0]["evidence"] == "menu is open Settings is visible"


def test_guard_ignores_invalid_progress_metadata_without_losing_judgement():
    def policy(messages, images, schema):
        return {
            "judgement": "unknown",
            "progress_updates": [{"node_id": "S1", "status": "verified"}],
            "reason": "more evidence needed",
        }

    proposal = SimpleNamespace(to_dict=lambda: {}, subgoal_id="S1")
    backend = MLLMBackend(MockModelClient(policy), max_parse_retries=0)
    result = backend.verify(
        State(), Observation(step=1, screenshot=b"a"), proposal,
        Observation(step=2, screenshot=b"b"))
    assert result.judgement == "unknown"
    assert result.progress_updates == []
    assert "Ignored unsafe progress metadata" in result.reason
    assert backend.progress_update_drop_count == 1


def test_guard_parse_exhaustion_fails_open_as_inconclusive_unknown():
    def policy(messages, images, schema):
        return {"judgement": "not-a-judgement"}

    proposal = SimpleNamespace(to_dict=lambda: {}, subgoal_id="S1")
    backend = MLLMBackend(MockModelClient(policy), max_parse_retries=0)
    result = backend.verify(
        State(), Observation(step=1, screenshot=b"a"), proposal,
        Observation(step=2, screenshot=b"b"))
    assert result.judgement == "unknown"
    assert result.unknown_reason == "verifier_inconclusive"
    assert "could not be parsed safely" in result.reason
    assert backend.parse_fail_open_count == 1


def test_executor_scales_qwen_normalized_coordinates_to_screen_pixels():
    def policy(messages, images, schema):
        return {
            "subgoal_id": "S1", "intent": "click menu", "expected_effect": "menu opens",
            "action": {"type": "click", "x": 1000, "y": 500}, "is_finish": False,
        }

    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(1920, 1080), coordinate_scale=1000)
    result = executor.act(Observation(step=1, screenshot=b"png"), State())
    assert result.action == {"type": "click", "x": 1919, "y": 540}


def test_executor_retries_when_model_selects_verified_subgoal():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        node = "S1" if calls[0] == 1 else "S2"
        return {
            "subgoal_id": node, "intent": "click", "expected_effect": "visible",
            "action": {"type": "click", "x": 10, "y": 10}, "is_finish": False,
        }

    state = SimpleNamespace(serialize=lambda: {
        "nodes": {"S1": {"status": "verified"}, "S2": {"status": "pending"}},
    })
    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(100, 100))
    result = executor.act(Observation(step=1, screenshot=b"png"), state)
    assert calls[0] == 2
    assert result.subgoal_id == "S2"


def test_executor_retries_when_model_selects_blocked_subgoal():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        node = "S2" if calls[0] == 1 else "S1"
        return {
            "subgoal_id": node, "intent": "click", "expected_effect": "visible",
            "action": {"type": "click", "x": 10, "y": 10}, "is_finish": False,
        }

    state = SimpleNamespace(serialize=lambda: {"nodes": {
        "S1": {"status": "executed", "dependencies": []},
        "S2": {"status": "pending", "dependencies": ["S1"]},
    }})
    executor = MLLMExecutor(MockModelClient(policy), "Do the task",
                            bounds=ActionBounds(100, 100))
    assert executor.act(Observation(step=1, screenshot=b"png"), state).subgoal_id == "S1"
    assert calls[0] == 2


def test_executor_allows_unknown_retry_until_runner_confirms_no_effect():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        action = ({"type": "hotkey", "keys": ["ctrl", "a"]}
                  if calls[0] == 1 else {"type": "click", "x": 50, "y": 50})
        return {
            "subgoal_id": "S1", "intent": "select", "expected_effect": "selected",
            "action": action, "is_finish": False,
        }

    repeated = {"step": 1, "subgoal": "S1",
                "action": {"type": "hotkey", "keys": ["ctrl", "a"]},
                "guard_judgement": "unknown"}
    history = SimpleNamespace(recent=lambda: [repeated, {**repeated, "step": 2}])
    executor = MLLMExecutor(MockModelClient(policy), "Do the task", history=history,
                            bounds=ActionBounds(100, 100))
    result = executor.act(Observation(step=3, screenshot=b"png"), State())
    assert calls[0] == 1
    assert result.action == {"type": "hotkey", "keys": ["ctrl", "a"]}


def test_executor_rejects_click_near_blocked_no_effect_region():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        action = ({"type": "click", "x": 130, "y": 125}
                  if calls[0] == 1 else {"type": "hotkey", "keys": ["tab"]})
        return {
            "subgoal_id": "S1", "intent": "change strategy",
            "expected_effect": "focus changes", "action": action, "is_finish": False,
        }

    history = SimpleNamespace(
        recent=lambda: [],
        blocked_actions=lambda: [{
            "subgoal_id": "S1", "action": {"type": "click", "x": 100, "y": 100},
            "reason": "no effect",
        }],
    )
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", history=history,
        bounds=ActionBounds(200, 200))

    result = executor.act(Observation(step=3, screenshot=b"png"), State())

    assert calls[0] == 2
    assert result.action == {"type": "hotkey", "keys": ["tab"]}


def test_executor_uses_focus_change_when_model_ignores_blocked_click_region():
    calls = [0]

    def policy(messages, images, schema):
        calls[0] += 1
        return {
            "subgoal_id": "S1", "intent": "repeat blocked click",
            "expected_effect": "none", "action": {"type": "click", "x": 120, "y": 120},
            "is_finish": False,
        }

    history = SimpleNamespace(
        recent=lambda: [],
        blocked_actions=lambda: [{
            "subgoal_id": "S1", "action": {"type": "click", "x": 100, "y": 100},
        }],
    )
    executor = MLLMExecutor(
        MockModelClient(policy), "Do the task", history=history,
        bounds=ActionBounds(200, 200), max_parse_retries=1)

    result = executor.act(Observation(step=3, screenshot=b"png"), State())

    assert calls[0] == 2
    assert result.action == {"type": "hotkey", "keys": ["tab"]}
    assert result.subgoal_done is False
