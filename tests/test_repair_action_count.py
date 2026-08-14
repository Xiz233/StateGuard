import json

from tests.validity_helpers import run_earlier


def test_repair_action_count_comes_from_environment_actions(tmp_path):
    result, episode = run_earlier(tmp_path)
    rows = [json.loads(line) for line in (episode / "trajectory.jsonl").read_text().splitlines()]
    assert result["repair_action_count"] == sum(r["execution_phase"] == "repair" for r in rows)
    assert result["repair_action_count"] == 3
