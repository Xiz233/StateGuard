from types import SimpleNamespace

from integrations.osworld import FakeOSWorldBackend


def test_latent_fault_changes_internal_state_before_visible_exposure():
    backend = FakeOSWorldBackend()
    task = {"initial_state": {"target": "none"}, "action_rules": [
        {"match": {"type": "click", "x": 2}, "effect": {"target": "bad"}}]}
    backend.reset(task)
    spec = {"exposure": {"mode": "latent", "hidden_state_keys": ["target"]}}
    backend.note_fault_injection(SimpleNamespace(), spec)
    hidden = backend.execute_action({"type": "click", "x": 2})
    assert backend.state["target"] == "bad"
    assert hidden["structured_state"]["target"] == "none"
    backend.expose_failure(SimpleNamespace())
    assert backend.get_observation()["structured_state"]["target"] == "bad"
