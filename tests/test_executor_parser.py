import pytest

from stateguard.executor.parser import parse_executor_output


def test_executor_parser_rejects_unknown_action():
    base = {"subgoal_id": "S1", "intent": "x", "expected_effect": "y", "is_finish": False}
    with pytest.raises(ValueError):
        parse_executor_output({**base, "action": {"type": "guess"}})
    assert parse_executor_output({**base, "action": {"type": "click", "x": 1, "y": 2}}).subgoal_id == "S1"
