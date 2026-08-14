import json

import pytest

from experiments.poc.config import load_config
from experiments.poc.runner import run_experiment, validate_graph
from stateguard.executor.parser import ActionBounds, validate_action
from stateguard.runtime.history import ActionHistory


def test_history_is_bounded():
    history = ActionHistory(10)
    for i in range(15): history.append(i)
    assert history.recent() == list(range(5, 15))


def test_coordinate_validation():
    with pytest.raises(ValueError): validate_action({"type": "click", "x": 100, "y": 1}, ActionBounds(100, 100))


def test_unapproved_graph_rejected(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"graph": {"approved": False}, "nodes": []}))
    with pytest.raises(ValueError): validate_graph(path)


def test_fake_dry_run_and_single_task():
    config = load_config("configs/poc/fake_osworld.yaml")
    result = run_experiment(config, "stateguard", "fake_wrong_target", dry_run=True,
                            allow_dirty=True)
    assert result["status"] == "dry_run_ready"


def test_fake_run_logging_and_resume(tmp_path):
    config = load_config("configs/poc/fake_osworld.yaml")
    config["experiment"] = {**config["experiment"], "output_dir": str(tmp_path)}
    summary = run_experiment(config, "stateguard", "fake_wrong_target", allow_dirty=True)
    assert summary["episodes"] == 2 and summary["task_success_rate"] == 1
    run = tmp_path / "fake_osworld_phase2b-stateguard"
    assert (run / "run_metadata.json").exists() and (run / "results.csv").exists()
    episodes = list((run / "episodes").iterdir())
    assert all((p / "trajectory.jsonl").exists() and (p / "model_usage.json").exists()
               for p in episodes)
    resumed = run_experiment(config, "stateguard", "fake_wrong_target", resume=True,
                             allow_dirty=True)
    assert resumed == summary
