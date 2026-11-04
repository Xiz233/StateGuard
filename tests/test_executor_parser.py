import pytest

from stateguard.executor.parser import parse_executor_output


def test_executor_parser_rejects_unknown_action():
    base = {"subgoal_id": "S1", "intent": "x", "expected_effect": "y", "is_finish": False}
    with pytest.raises(ValueError):
        parse_executor_output({**base, "action": {"type": "guess"}})
    assert parse_executor_output({**base, "action": {"type": "click", "x": 1, "y": 2}}).subgoal_id == "S1"


def test_parser_normalizes_click_capabilities_and_observability():
    base = {
        "subgoal_id": "S1", "intent": "open", "expected_effect": "window opens",
        "effect_observability": "visual", "is_finish": False,
    }
    proposal = parse_executor_output({
        **base, "action": {"type": "double_click", "x": 4, "y": 5},
    })
    assert proposal.action == {"type": "click", "x": 4, "y": 5, "clicks": 2}
    assert proposal.effect_observability == "visual"
