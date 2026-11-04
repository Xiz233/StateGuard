import json
from pathlib import Path

from experiments.poc.config import load_config
from experiments.poc.logging import EpisodeLogger
from experiments.poc.runner import run_experiment
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import ActionProposal
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.training_logging import RecordingModelClient, TrainingReadyLogger


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def _state():
    return compile_from_spec({"nodes": [{
        "node_id": "S1", "description": "S1", "dependencies": [],
        "expected_result_semantic": "S1 achieved",
    }]})


def test_fake_episode_dual_writes_complete_training_evidence(tmp_path):
    config = load_config("configs/poc/fake_osworld.yaml")
    config["experiment"]["output_dir"] = str(tmp_path)
    config["experiment"]["name"] = "training_logging"
    run_experiment(
        config, "stateguard", selected="fake_wrong_target",
        scenario="clean", allow_dirty=True)

    episode = (tmp_path / "training_logging-stateguard" / "episodes"
               / "fake_wrong_target--stateguard--clean")
    events = _rows(episode / "events.jsonl")
    calls = _rows(episode / "model_calls.jsonl")
    artifacts = _rows(episode / "artifact_manifest.jsonl")

    assert (episode / "trajectory.jsonl").exists()
    assert any(row.get("event_type") == "finish_decision"
               and row.get("event_phase") == "completed" for row in events)
    assert any(row.get("event_type") == "environment_transition"
               and row.get("execution_receipt", {}).get("success") is True
               for row in events)
    call_rows = [row for row in calls if row.get("record_type") == "call"]
    call_starts = [row for row in calls if row.get("record_type") == "call_started"]
    assert len(call_starts) == len(call_rows)
    assert {row["call_id"] for row in call_starts} == {
        row["call_id"] for row in call_rows}
    assert call_rows and all(row.get("request", {}).get("messages") for row in call_rows)
    assert all(row.get("raw_text") for row in call_rows)
    assert artifacts and all(row.get("artifact_id") and row.get("sha256")
                             for row in artifacts)
    evaluator = json.loads((episode / "evaluator_result.json").read_text())
    assert evaluator["score"] == 1.0
    assert evaluator["details"]["state"] == {"target": "good", "value": "ok"}


def test_executor_parse_failure_is_a_logical_event(tmp_path):
    class FailingExecutor:
        calls = tokens = 0
        latency = 0.0

        def act(self, *_args, **_kwargs):
            raise ValueError("invalid action payload")

    logger = EpisodeLogger(tmp_path / "episode", {"task_id": "t"}, {"nodes": []})
    runner = EpisodeRunner(FailingExecutor(), max_total_steps=1, mode="executor_only")
    result = runner.run(
        OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), _state(),
        {"initial_state": {}, "success_state": {}, "action_rules": []}, logger=logger)

    assert result.status == "executor_parse_failed"
    events = _rows(tmp_path / "episode" / "events.jsonl")
    assert any(row.get("event_type") == "executor_decision"
               and row.get("event_phase") == "failed"
               and row.get("failure_type") == "parse_failure" for row in events)


def test_environment_exception_has_failed_receipt(tmp_path):
    class Executor:
        calls = tokens = 0
        latency = 0.0

        def act(self, *_args, **_kwargs):
            return ActionProposal(
                "S1", {"type": "click", "x": 1, "y": 1},
                "click", "visible change", False, False)

    class BrokenBackend(FakeOSWorldBackend):
        def execute_action(self, action):
            raise RuntimeError("desktop transport failed")

    logger = EpisodeLogger(tmp_path / "episode", {"task_id": "t"}, {"nodes": []})
    runner = EpisodeRunner(Executor(), max_total_steps=1, mode="executor_only")
    result = runner.run(
        OSWorldAdapter(BrokenBackend(), (10, 10)), _state(),
        {"initial_state": {}, "success_state": {}, "action_rules": []}, logger=logger)

    assert result.status == "environment_failed"
    events = _rows(tmp_path / "episode" / "events.jsonl")
    failed = next(row for row in events
                  if row.get("event_type") == "environment_transition"
                  and row.get("event_phase") == "failed")
    assert failed["execution_receipt"]["success"] is False
    assert "desktop transport failed" in failed["execution_receipt"]["exception"]


def test_parse_retry_has_stable_call_and_intervention_links(tmp_path):
    responses = iter([
        {"subgoal_id": "missing-fields"},
        {"subgoal_id": "S1", "intent": "click", "expected_effect": "visible",
         "effect_observability": "visual",
         "action": {"type": "click", "x": 1, "y": 1},
         "subgoal_done": False, "is_finish": False},
    ])
    recorder = TrainingReadyLogger(tmp_path)
    client = RecordingModelClient(
        MockModelClient(lambda *_args: next(responses)), recorder, "executor")
    executor = MLLMExecutor(
        client, "test", bounds=ActionBounds(10, 10), max_parse_retries=1)
    event_id = recorder.start_event("executor_decision", 1, _state().serialize())
    with recorder.bind_event(event_id):
        proposal = executor.act(Observation(screenshot=None), _state())
    assert proposal.subgoal_id == "S1"

    calls = [row for row in _rows(tmp_path / "model_calls.jsonl")
             if row.get("record_type") == "call"]
    assert calls[1]["retry_of_call_id"] == calls[0]["call_id"]
    interventions = _rows(tmp_path / "interventions.jsonl")
    assert interventions[0]["intervention_type"] == "retry"
    assert interventions[0]["parent_event_id"] == event_id
    assert calls[1]["retry_intervention_id"] == interventions[0]["intervention_id"]
