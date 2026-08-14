from tests.validity_helpers import run_earlier


def test_repair_cycle_count_is_not_action_count(tmp_path):
    result, _ = run_earlier(tmp_path)
    assert result["repair_cycle_count"] == 1
    assert result["repair_action_count"] > result["repair_cycle_count"]
