import json

from experiments.poc.runner import _stored_episode_results


def test_stored_episode_results_loads_all_valid_completed_attempts(tmp_path):
    for name, value in (("a", {"status": "completed"}),
                        ("b", {"status": "max_steps"})):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(value), encoding="utf-8")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "result.json").write_text("not-json", encoding="utf-8")

    assert [item["status"] for item in _stored_episode_results(tmp_path)] == [
        "completed", "max_steps"]
