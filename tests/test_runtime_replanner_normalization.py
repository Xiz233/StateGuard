from stateguard.planning.runtime_replanner import (
    LocalReplanRequest, MLLMPlanPatchProvider,
)
from stateguard.models.mock import MockModelClient


def _request():
    invariant = "The requested setting remains enabled"
    return LocalReplanRequest(
        task_goal="enable setting",
        problem_node={
            "node_id": "S2",
            "description": "enable setting",
            "required": True,
            "semantic_goal": {"description": invariant, "invariant": invariant,
                              "required": True, "role": None},
            "verification_intent": {"target_claim": invariant,
                                    "preferred_evidence_types": ["visual"],
                                    "persistence_required": False, "strength": "normal"},
        },
        ancestor_boundary=(), descendant_boundary=(),
        current_observation_summary={"has_screenshot": True},
        environment_capabilities={
            "available_sources": ["screenshot"],
            "supported_verifiers": ["visual_mllm"],
        },
        verification_debt_summary={},
    )


def test_replanner_binds_missing_protocol_and_immutable_anchor_semantics():
    def policy(messages, images, schema):
        return {"patch": {"new_nodes": [{
            "node_id": "S2_retry",
            "description": "retry through another route",
            "dependencies": [],
            "unexpected_model_note": "must not reach TaskNode.from_dict",
            "semantic_goal": {"description": "easier", "invariant": "easier"},
            "evidence_contract": {
                "contract_id": "model-contract", "evidence_type": "visual",
                "sources": ["screenshot"], "success_condition": "easier",
                "version": 1, "provenance": "manual",
            },
        }]}}

    patch = MLLMPlanPatchProvider(MockModelClient(policy), max_attempts=1).propose_patch(
        _request())
    anchor = patch.new_nodes[0]
    assert patch.trigger_node_id == "S2"
    assert patch.replace_nodes == ("S2",)
    assert patch.replacement_anchor == "S2_retry"
    assert anchor["semantic_goal"]["invariant"] == "The requested setting remains enabled"
    assert anchor["evidence_contract"]["success_condition"] == (
        "The requested setting remains enabled")
    assert "provenance" not in anchor["evidence_contract"]
    assert "unexpected_model_note" not in anchor


def test_replanner_infers_unique_sink_as_anchor():
    def policy(messages, images, schema):
        return {"new_nodes": [
            {"node_id": "prepare", "description": "prepare", "dependencies": [],
             "semantic_goal": {"invariant": "ready"}},
            {"node_id": "confirm", "description": "confirm",
             "dependencies": ["prepare"], "semantic_goal": {"invariant": "confirmed"}},
        ]}

    patch = MLLMPlanPatchProvider(MockModelClient(policy), max_attempts=1).propose_patch(
        _request())
    assert patch.replacement_anchor == "confirm"


def test_replanner_falls_back_to_semantic_preserving_retry_node():
    def policy(messages, images, schema):
        return {"ungroundable": True, "reason": "no patch proposed"}

    provider = MLLMPlanPatchProvider(MockModelClient(policy), max_attempts=2)
    patch = provider.propose_patch(_request())
    node = patch.new_nodes[0]
    assert provider.calls == 2
    assert provider.fallback_count == 1
    assert patch.trigger_node_id == "S2"
    assert patch.replacement_anchor.startswith("S2__retry_")
    assert node["semantic_goal"]["invariant"] == "The requested setting remains enabled"
    assert node["evidence_contract"]["sources"] == ["screenshot"]
