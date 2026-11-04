import csv
import json

import pytest

from experiments.poc.config import load_config
from experiments.poc.logging import RunLogger
from experiments.poc.runner import (
    _load_episode_result, run_experiment, validate_graph,
)
from integrations.osworld import FakeOSWorldBackend
from stateguard.executor.parser import ActionBounds, validate_action
from stateguard.runtime.episode_runner import EpisodeRunner
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


def test_scenario_selects_one_fault_without_clean(tmp_path):
    config = load_config("configs/poc/fake_osworld.yaml")
    config["experiment"] = {**config["experiment"], "output_dir": str(tmp_path)}
    task = next(task for task in config["tasks"] if task["task_id"] == "fake_wrong_target")
    fault_id = task["faults"][0]["fault_id"]

    summary = run_experiment(
        config, "stateguard", "fake_wrong_target", allow_dirty=True, scenario=fault_id
    )

    assert summary["episodes"] == 1
    assert summary["fault_injection_validity_rate"] == 1


def test_unknown_scenario_is_rejected():
    config = load_config("configs/poc/fake_osworld.yaml")

    with pytest.raises(ValueError, match="unknown scenario"):
        run_experiment(
            config,
            "stateguard",
            "fake_wrong_target",
            dry_run=True,
            allow_dirty=True,
            scenario="missing-fault",
        )


def test_environment_closes_when_episode_runner_raises(tmp_path, monkeypatch):
    closed = []

    def fail_run(*args, **kwargs):
        raise RuntimeError("unexpected episode failure")

    monkeypatch.setattr(EpisodeRunner, "run", fail_run)
    monkeypatch.setattr(FakeOSWorldBackend, "close", lambda self: closed.append(True))
    config = load_config("configs/poc/fake_osworld.yaml")
    config["experiment"] = {**config["experiment"], "output_dir": str(tmp_path)}

    with pytest.raises(RuntimeError, match="unexpected episode failure"):
        run_experiment(
            config, "stateguard", "fake_wrong_target", allow_dirty=True,
            scenario="clean")

    assert closed == [True]


def test_corrupt_episode_result_is_not_resumable(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text("{not-json", encoding="utf-8")

    assert _load_episode_result(result_path) is None


def test_results_csv_accepts_mixed_episode_schemas(tmp_path):
    path = tmp_path / "results.csv"

    RunLogger.write_results_csv(path, [
        {"task_id": "old", "success": False},
        {"task_id": "new", "success": True, "new_metric": 3},
    ])

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["new_metric"] == ""
    assert rows[1]["new_metric"] == "3"
