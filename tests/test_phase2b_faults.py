from types import SimpleNamespace

from experiments.poc.faults import make_injector


def proposal(action, node="S1"):
    return SimpleNamespace(subgoal_id=node, action=action,
                           to_dict=lambda: {"subgoal_id": node, "action": action})


def spec(kind, mutation):
    return {"fault_id": kind, "type": kind, "root_node": "S1",
            "inject": {"trigger": {"subgoal_id": "S1"}, "mutation": mutation}}


def test_all_faults_mutate_executed_action():
    cases = [
        ("wrong_target", {"action_override": {"type": "click", "x": 2, "y": 2}},
         {"type": "click", "x": 1, "y": 1}),
        ("wrong_value", {"replace_text": "bad"}, {"type": "type", "text": "ok"}),
        ("no_effect", {}, {"type": "click", "x": 1, "y": 1}),
        ("earlier_state_corruption", {"action_override": {"type": "click", "x": 2, "y": 2}},
         {"type": "click", "x": 1, "y": 1}),
    ]
    for kind, mutation, original in cases:
        executed, event = make_injector(spec(kind, mutation)).inject("t", 1, proposal(original), None)
        assert event and executed != original


def test_fault_ground_truth_not_in_runtime_model_inputs():
    from stateguard.guard.backends.mllm_backend import MLLMBackend
    from stateguard.models.mock import MockModelClient
    captured = {}
    def policy(messages, images, schema):
        captured["prompt"] = messages[0]["content"]
        return {"judgement": "unknown", "progress_updates": [], "fault_root": None,
                "fault_type": None, "verification_target": "inspect", "reason": "unclear"}
    backend = MLLMBackend(MockModelClient(policy))
    state = SimpleNamespace(serialize=lambda: {"nodes": {}}, __contains__=lambda s, x: False)
    obs = SimpleNamespace(to_dict=lambda: {}, screenshot=None)
    prop = SimpleNamespace(to_dict=lambda: {}, subgoal_id="S1")
    backend.verify(state, obs, prop, obs)
    assert all(key not in captured["prompt"] for key in ("fault_id", "root_node", "expected_affected"))
