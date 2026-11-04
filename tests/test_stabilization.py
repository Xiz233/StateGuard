import json

import pytest

from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import ActionProposal, GuardResult
from stateguard.executor.parser import parse_executor_output
from stateguard.guard.backends.mllm_backend import (
    GuardCallBudgetExceeded, MLLMBackend,
)
from stateguard.interfaces.observation import Observation
from stateguard.models.mock import MockModelClient
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.training_logging import TrainingReadyLogger


def state():
    return compile_from_spec({"nodes": [{
        "node_id": "S1", "description": "S1", "dependencies": [],
        "expected_result_semantic": "S1 achieved",
    }]})


def test_unknown_type_is_inferred_from_existing_visible_evidence():
    result = GuardResult(
        "unknown", verification_target="Confirm the visible terminal prompt",
        reason="The after screenshot positively shows a focused terminal prompt.",
        unknown_reason="verifier_inconclusive",
        evidence_gap={"available_evidence": ["focused terminal prompt"],
                      "missing_evidence": []})
    assert result.to_dict()["unknown_type"] == "guard_capability_insufficient"


def test_executor_parser_normalizes_safe_wrapper_and_aliases():
    proposal = parse_executor_output({"proposal": {
        "subgoal": "S1", "intent": "click", "expected_result": "visible",
        "action": {"type": "wait"}, "finish": False,
    }})
    assert proposal.subgoal_id == "S1"
    assert proposal.expected_effect == "visible"


def test_consecutive_unknown_budget_has_explicit_status():
    class Executor:
        calls = tokens = 0
        latency = 0.0

        def act(self, *_args):
            self.calls += 1
            return ActionProposal(
                "S1", {"type": "wait"}, "wait", "visible", False, False)

    class Guard:
        def verify_transition(self, *_args, **_kwargs):
            return GuardResult(
                "unknown", verification_target="Obtain visible evidence",
                reason="No visible change", unknown_reason="need_more_evidence")

    result = EpisodeRunner(
        Executor(), Guard(), max_total_steps=5, mode="stateguard",
        max_consecutive_unknown=2,
    ).run(
        OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state(),
        {"initial_state": {}, "success_state": {"done": True},
         "action_rules": []})
    assert result.status == "unknown_budget_exhausted"
    assert result.total_steps == 2
    assert result.max_consecutive_unknown_observed == 2


def test_unknown_resolution_sidecar_is_append_only(tmp_path):
    logger = TrainingReadyLogger(tmp_path)
    result = GuardResult(
        "unknown", verification_target="Inspect output",
        reason="Evidence is missing", unknown_reason="need_more_evidence")
    logger.record_unknown("evt-1", 1, "S1", result.to_dict(), ["artifact-1"])
    logger.resolve_unknowns(
        "S1", "VALID", 2, ["artifact-2"], "later_state")
    rows = [json.loads(line) for line in
            (tmp_path / "unknown_resolutions.jsonl").read_text().splitlines()]
    assert [row["resolution"] for row in rows] == ["PENDING", "VALID"]
    assert rows[0]["unknown_type"] == "evidence_insufficient"


def test_guard_model_call_budget_is_hard():
    response = {
        "judgement": "unknown", "verification_target": "inspect",
        "unknown_reason": "need_more_evidence", "progress_updates": [],
    }
    backend = MLLMBackend(MockModelClient([response]), max_total_calls=1)
    proposal = ActionProposal("S1", {"type": "wait"}, "wait", "visible")
    observation = Observation(step=1)
    backend.verify(state(), observation, proposal, observation)
    with pytest.raises(GuardCallBudgetExceeded):
        backend.verify(state(), observation, proposal, observation)
