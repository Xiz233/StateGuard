from types import SimpleNamespace

from stateguard.runtime.history import ActionHistory


def test_history_records_action_and_verification_feedback():
    history = ActionHistory()
    proposal = SimpleNamespace(
        subgoal_id="S2", action={"type": "hotkey", "keys": ["ctrl", "a"]},
        intent="select all", expected_effect="text selected")
    observation = SimpleNamespace(visible_text=None)
    guard = SimpleNamespace(
        judgement="unknown", verification_target="selection must be visible",
        reason="no highlight", progress_updates=[])
    history.add_transition(2, proposal, observation, guard)
    item = history.recent()[0]
    assert item["action"] == {"type": "hotkey", "keys": ["ctrl", "a"]}
    assert item["verification_target"] == "selection must be visible"
