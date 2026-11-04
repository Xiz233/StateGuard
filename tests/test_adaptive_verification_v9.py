import pytest

from stateguard.core.schema import (
    Evidence, GuardResult, NodeStatus, RepairRequest, TaskNode,
)
from stateguard.core.task_state import VerifiedTaskState
from stateguard.environment import EnvironmentCapabilities
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import ActionProposal
from stateguard.interfaces.observation import Observation
from stateguard.planning.plan_patch import PlanPatch
from stateguard.planning.runtime_replanner import RuntimeReplanner
from stateguard.runtime.adaptive_verification import (
    AdaptiveVerificationConfig, AdaptiveVerificationController,
)
from stateguard.runtime.checkpoint_policy import CompletionClaimTracker
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.runtime.verification_debt import VerificationDebtConfig
from stateguard.verification import EvidenceSource
from stateguard.verification.grounder import (
    GroundingTrigger, MLLMGroundingProvider, VerificationGrounder,
)
from stateguard.verification.registry import default_registry
from stateguard.verification.result import EvidenceResult
from stateguard.verification.validator import validate_contract
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter
from experiments.poc.runner import _osworld_available


def _registry():
    return default_registry(
        lambda contract, _observation: EvidenceResult.unknown(
            "visual_mllm", sources=contract.sources))


def _capabilities(*sources):
    return EnvironmentCapabilities(
        available_sources=frozenset(sources),
        supported_verifiers=frozenset({
            "visual_mllm", "structured_predicate", "accessibility_predicate",
        }),
    )


def _node(invariant="the requested value is visibly present"):
    return TaskNode(
        "S1", "complete the requested state",
        expected_result_semantic=invariant,
        evidence_mode="visual",
    )


def test_grounding_preserves_semantics_across_context_revision():
    node = _node()
    grounder = VerificationGrounder()
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    first = grounder.ground(
        node, Observation(step=1, screenshot=b"first"), caps).contract
    second = grounder.ground(
        node, Observation(step=2, screenshot=b"second"), caps, first,
        GroundingTrigger.CONTEXT_SHIFT).contract

    assert first.version == 1 and second.version == 2
    assert first.semantic_goal_ref == second.semantic_goal_ref == node.semantic_goal.reference
    assert second.success_condition == node.semantic_goal.invariant
    assert validate_contract(node, first, second, caps, _registry()).valid


def test_model_grounding_hints_cannot_rewrite_semantic_contract():
    class Response:
        parsed = {"grounding_hints": {
            "evidence_sources": ["visual"],
            "ui_anchor": {"text": "Save"},
            "confidence": 4.2,
            "success_condition": "weaker condition",
            "semantic_goal_ref": "changed",
        }}
        text = "{}"
        latency_seconds = 0.0
        usage = {}

    class Client:
        def generate(self, *_args, **_kwargs):
            return Response()

    node = _node("the exact requested value is visible")
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    contract = VerificationGrounder(MLLMGroundingProvider(Client())).ground(
        node, Observation(step=1, screenshot=b"screen"), caps).contract
    assert contract.semantic_goal_ref == node.semantic_goal.reference
    assert contract.success_condition == node.semantic_goal.invariant
    assert contract.observable_claims[0].expected_value == node.semantic_goal.invariant
    assert contract.observable_claims[0].ui_anchor == {"text": "Save"}
    assert contract.confidence == 1.0
    assert validate_contract(node, None, contract, caps, _registry()).valid


def test_invalid_model_source_falls_back_to_available_verified_source():
    class Provider:
        def ground(self, **_kwargs):
            return [{"sources": ["imaginary_dom_source"]}]

    node = _node()
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    result = VerificationGrounder(Provider()).ground(
        node, Observation(step=1, screenshot=b"screen"), caps)
    assert result.groundable
    assert result.contract.sources == (EvidenceSource.SCREENSHOT,)


def test_model_cannot_mark_temporarily_hidden_visual_goal_ungroundable():
    class Provider:
        def ground(self, **_kwargs):
            return {"ungroundable": True, "reason": "target is not visible yet"}

    result = VerificationGrounder(Provider()).ground(
        _node(), Observation(step=1, screenshot=b"screen"),
        _capabilities(EvidenceSource.SCREENSHOT),
    )
    assert result.groundable
    assert result.contract.preferred_verifier == "visual_mllm"


def test_validator_rejects_moving_goalpost():
    node = _node("the exact requested value is visible")
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    contract = VerificationGrounder().ground(
        node, Observation(step=1, screenshot=b"screen"), caps).contract
    value = contract.to_dict()
    value["success_condition"] = "some value is visible"
    value["observable_claims"][0]["expected_value"] = "some value is visible"
    weakened = type(contract).from_dict(value)

    result = validate_contract(node, None, weakened, caps, _registry())
    assert not result.valid
    assert not result.no_weakening


def test_unknown_debt_escalates_when_no_new_evidence_source_exists():
    node = _node()
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    controller = AdaptiveVerificationController(
        VerificationGrounder(), _registry(),
        AdaptiveVerificationConfig(
            debt=VerificationDebtConfig(soft_threshold=1,
                                        strategy_switch_threshold=2,
                                        hard_threshold=4)))
    observation = Observation(step=1, screenshot=b"screen")
    controller.ensure_contract(node, observation, caps)

    decision = None
    for step in range(1, 5):
        decision = controller.observe_result(
            node,
            GuardResult(
                "unknown", verification_target="show visible confirmation",
                reason="current image is inconclusive",
                unknown_reason="need_more_evidence",
                evidence_gap={"same_contract": True}),
            step, observation, caps,
        )

    assert decision.action.value == "unverifiable"
    assert controller.store.active("S1") is None
    assert controller.store.history("S1")[0].version == 1
    state = controller.debt.state_for("S1", node.semantic_goal.reference)
    assert state.consecutive_unknown == 4
    assert state.attempted_sources == {"screenshot"}


def test_unknown_debt_switches_to_an_untried_evidence_source():
    node = TaskNode(
        "S1", "set volume", structured_predicate={
            "field": "volume", "operator": "eq", "value": 50},
        evidence_mode="visual")
    caps = _capabilities(
        EvidenceSource.SCREENSHOT, EvidenceSource.STRUCTURED_STATE)
    controller = AdaptiveVerificationController(
        VerificationGrounder(), _registry(),
        AdaptiveVerificationConfig(
            debt=VerificationDebtConfig(soft_threshold=1,
                                        strategy_switch_threshold=2,
                                        hard_threshold=4)))
    observation = Observation(
        step=1, screenshot=b"screen", structured_state={"volume": None})
    controller.ensure_contract(node, observation, caps)
    first_source = controller.store.active("S1").sources[0]

    revised = False
    for step in range(1, 5):
        decision = controller.observe_result(
            node,
            GuardResult(
                "unknown", verification_target="confirm volume",
                reason="current evidence is inconclusive",
                unknown_reason="need_more_evidence",
                evidence_gap={"same_contract": True}),
            step, observation, caps,
        )
        revised = revised or decision.contract_revised

    active = controller.store.active("S1")
    assert revised
    assert active.version == 2
    assert active.sources[0] != first_source


def test_plan_patch_retires_old_contract_and_carries_source_memory():
    node = _node()
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    controller = AdaptiveVerificationController(VerificationGrounder(), _registry())
    observation = Observation(step=1, screenshot=b"screen")
    controller.ensure_contract(node, observation, caps)
    contract = controller.store.active("S1")
    controller.debt.update(
        "S1", contract,
        EvidenceResult.unknown(
            "visual_mllm", sources=contract.sources, target="more evidence"), 1)

    controller.on_plan_patch({"S1": "S1R"})

    assert controller.store.active("S1") is None
    state = controller.debt.state_for("S1R", node.semantic_goal.reference)
    assert state.attempted_sources == {"screenshot"}
    assert state.debt_score == 0
    assert state.consecutive_unknown == 0


def test_completion_claim_requires_information_gain_or_strategy_change():
    tracker = CompletionClaimTracker()
    assert tracker.should_verify("S1", "c1", "e1", "visual")
    assert not tracker.should_verify("S1", "c1", "e1", "visual")
    assert tracker.should_verify("S1", "c2", "e1", "visual")
    assert tracker.should_verify("S1", "c2", "e2", "visual")
    assert tracker.should_verify("S1", "c2", "e2", "structured")
    assert tracker.overclaim_count == 1


def test_grounder_returns_unverifiable_for_unavailable_sources():
    result = VerificationGrounder().ground(
        _node(), Observation(step=1), _capabilities())
    assert not result.groundable
    assert "no available source" in result.reason


def test_final_gate_requires_evidence_from_active_contract():
    node = _node()
    state = VerifiedTaskState({node.node_id: node})
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    controller = AdaptiveVerificationController(VerificationGrounder(), _registry())
    controller.ensure_contract(node, Observation(step=1, screenshot=b"screen"), caps)
    active = controller.store.active(node.node_id)
    state.mark_active(node.node_id)
    state.mark_executed(node.node_id)
    state.mark_verified(node.node_id, Evidence(1, "guard", "visible", 0.9,
                                               contract_id="old-contract"))
    assert not controller.final_invariants_hold(state)
    node.evidence[0].contract_id = active.contract_id
    assert controller.final_invariants_hold(state)


@pytest.mark.parametrize("category,invariant", [
    ("browser_navigation", "the requested page identity is visible"),
    ("application_setting", "the requested setting value is active"),
    ("file_operation", "the requested file state is externally confirmed"),
    ("document_editing", "the requested document content is visible"),
    ("form_entry", "the requested values are shown as submitted"),
])
def test_same_grounding_core_supports_five_task_categories(category, invariant):
    node = TaskNode(category, category, expected_result_semantic=invariant)
    caps = _capabilities(EvidenceSource.SCREENSHOT)
    contract = VerificationGrounder().ground(
        node, Observation(step=1, screenshot=b"screen"), caps).contract
    assert contract.semantic_goal_ref == node.semantic_goal.reference
    assert validate_contract(node, None, contract, caps, _registry()).valid


def test_episode_continues_after_valid_local_replan_and_preserves_progress():
    state = compile_from_spec({"nodes": [
        {"node_id": "A", "description": "A", "dependencies": [],
         "expected_result_semantic": "A visible"},
        {"node_id": "B", "description": "B", "dependencies": ["A"],
         "expected_result_semantic": "B visible"},
        {"node_id": "C", "description": "C", "dependencies": ["B"],
         "expected_result_semantic": "C visible"},
    ]})
    state.mark_active("A")
    state.mark_executed("A")
    state.mark_verified("A", Evidence(0, "test", "A visible", 1.0))

    class Executor:
        def __init__(self):
            self.nodes = iter(("B", "B1"))
            self.calls = 0

        def act(self, _observation, _state, _context=None):
            self.calls += 1
            node_id = next(self.nodes)
            return ActionProposal(
                node_id, {"type": "click", "x": 1, "y": 1},
                intent="advance", subgoal_done=True)

    class Guard:
        def verify_transition(self, task_state, _before, proposal, after, **_kwargs):
            if proposal.subgoal_id == "B":
                return GuardResult(
                    "unknown", unknown_reason="node_unverifiable",
                    verification_target="replace this semantic boundary")
            contract_id = task_state.get("B1").active_contract_id
            return GuardResult("verified", state_updates=[{
                "op": "verify", "node_id": "B1", "evidence": {
                    "step_id": after.step, "source": "test", "description": "visible",
                    "confidence": 1.0, "contract_id": contract_id,
                }}])

    class PatchProvider:
        def propose_patch(self, _request):
            invariant = "B visible"
            return PlanPatch(
                trigger_node_id="B", replace_nodes=("B",),
                new_nodes=({
                    "node_id": "B1", "description": "replacement", "dependencies": ["A"],
                    "required": True,
                    "semantic_goal": {"description": invariant, "invariant": invariant},
                    "verification_intent": {
                        "target_claim": invariant,
                        "preferred_evidence_types": ["visual"],
                    },
                    "evidence_contract": {
                        "contract_id": "B1-provisional", "evidence_type": "visual",
                        "sources": ["screenshot"], "success_condition": invariant,
                        "allow_mllm_fallback": True,
                    },
                },),
                dependency_rewrites={}, replacement_anchor="B1",
                preserved_node_ids=("A",), rationale="observable replacement")

    controller = AdaptiveVerificationController(VerificationGrounder(), _registry())
    executor = Executor()
    result = EpisodeRunner(
        executor, Guard(), max_total_steps=2, mode="stateguard",
        verification_policy="sparse", adaptive_controller=controller,
        runtime_replanner=RuntimeReplanner(PatchProvider()),
    ).run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {"done": True}, "action_rules": []})

    assert result.local_replan_success_count == 1
    assert executor.calls == 2
    assert result.task_state.get("A").status.value == "verified"
    assert result.task_state.get("A").evidence[0].description == "A visible"
    assert "B" not in result.task_state and "B1" in result.task_state
    assert result.task_state.get("C").dependencies == ["B1"]


def test_active_repair_follows_its_root_across_local_replan():
    state = compile_from_spec({"nodes": [{
        "node_id": "S1R", "description": "restore the visible result",
        "dependencies": [], "expected_result_semantic": "result is visible",
    }]})

    class Executor:
        def __init__(self):
            self.nodes = iter(("S1R", "S1R", "S1R-P"))
            self.calls = 0
            self.context_roots = []

        def act(self, _observation, _state, context=None):
            self.calls += 1
            self.context_roots.append(getattr(context, "fault_root", None))
            return ActionProposal(
                next(self.nodes), {"type": "click", "x": 1, "y": 1},
                intent="advance", subgoal_done=True)

    class Guard:
        def __init__(self):
            self.calls = 0

        def verify_transition(self, task_state, _before, proposal, after, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return GuardResult(
                    "contradicted", fault_root="S1R", fault_type="no_effect",
                    state_updates=[
                        {"op": "active", "node_id": "S1R"},
                        {"op": "execute", "node_id": "S1R"},
                        {"op": "fail", "node_id": "S1R"},
                    ],
                    repair=RepairRequest(
                        "S1R", "no_effect", "restore result",
                        reverify_nodes=["S1R"], confidence=0.9))
            if self.calls == 2:
                return GuardResult(
                    "unknown",
                    state_updates=[
                        {"op": "active", "node_id": "S1R"},
                        {"op": "execute", "node_id": "S1R"},
                    ],
                    unknown_reason="node_unverifiable",
                    verification_target="use a replacement route")
            contract_id = task_state.get(proposal.subgoal_id).active_contract_id
            return GuardResult("verified", state_updates=[
                {"op": "active", "node_id": "S1R-P"},
                {"op": "execute", "node_id": "S1R-P"},
                {"op": "verify", "node_id": "S1R-P", "evidence": {
                    "step_id": after.step, "source": "test", "description": "visible",
                    "confidence": 1.0, "contract_id": contract_id,
                }},
            ])

    class PatchProvider:
        def propose_patch(self, _request):
            invariant = "result is visible"
            return PlanPatch(
                trigger_node_id="S1R", replace_nodes=("S1R",),
                new_nodes=({
                    "node_id": "S1R-P", "description": "replacement route",
                    "dependencies": [], "required": True,
                    "semantic_goal": {"description": invariant, "invariant": invariant},
                    "verification_intent": {
                        "target_claim": invariant,
                        "preferred_evidence_types": ["visual"],
                    },
                    "evidence_contract": {
                        "contract_id": "S1R-P-provisional", "evidence_type": "visual",
                        "sources": ["screenshot"], "success_condition": invariant,
                        "allow_mllm_fallback": True,
                    },
                },), dependency_rewrites={}, replacement_anchor="S1R-P",
                rationale="replace an exhausted route")

    executor = Executor()
    controller = AdaptiveVerificationController(VerificationGrounder(), _registry())
    result = EpisodeRunner(
        executor, Guard(), max_total_steps=3, mode="stateguard",
        verification_policy="dense", adaptive_controller=controller,
        runtime_replanner=RuntimeReplanner(PatchProvider()),
    ).run(
        OSWorldAdapter(FakeOSWorldBackend(), (100, 100)), state,
        {"initial_state": {}, "success_state": {}, "action_rules": []})

    assert result.local_replan_success_count == 1
    assert "S1R" not in result.task_state
    assert result.task_state.get("S1R-P").status == NodeStatus.VERIFIED
    assert executor.context_roots == [None, "S1R", "S1R-P"]
    assert result.repair_action_count == 2
    assert result.reactivated_nodes == ["S1R-P"]


def test_osworld_source_root_satisfies_dry_run_probe(tmp_path):
    assert not _osworld_available(tmp_path)
    (tmp_path / "desktop_env").mkdir()
    assert _osworld_available(tmp_path)
import pytest
