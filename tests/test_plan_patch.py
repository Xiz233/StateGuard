from copy import deepcopy

import pytest

from stateguard.environment import EnvironmentCapabilities
from stateguard.planning import PlanPatch, apply_plan_patch, validate_plan_patch
from stateguard.verification import EvidenceSource


def _visual_contract(contract_id):
    return {
        "contract_id": contract_id,
        "evidence_type": "visual",
        "sources": ["screenshot"],
        "success_condition": f"{contract_id} is visible",
        "allow_mllm_fallback": True,
    }


def _semantic(node_id):
    invariant = f"{node_id} is visible"
    return {
        "semantic_goal": {"description": invariant, "invariant": invariant},
        "verification_intent": {
            "target_claim": invariant,
            "preferred_evidence_types": ["visual"],
        },
    }


def _nodes():
    return {
        "A": {
            "node_id": "A",
            "dependencies": [],
            "required": True,
            "status": "verified",
            "evidence": [{"kind": "visual", "value": "A"}],
            "evidence_contract": _visual_contract("A-contract"),
        },
        "B": {
            "node_id": "B",
            "dependencies": ["A"],
            "required": True,
            "status": "unverifiable",
            "evidence": [],
            "evidence_contract": _visual_contract("B-contract"),
        },
        "C": {
            "node_id": "C",
            "dependencies": ["B"],
            "required": True,
            "status": "pending",
            "evidence": [],
            "evidence_contract": _visual_contract("C-contract"),
        },
    }


def _patch():
    return PlanPatch(
        trigger_node_id="B",
        replace_nodes=("B",),
        new_nodes=(
            {
                "node_id": "B1",
                **_semantic("B1-contract"),
                "dependencies": ["A"],
                "required": True,
                "status": "pending",
                "evidence": [],
                "evidence_contract": _visual_contract("B1-contract"),
            },
            {
                "node_id": "B2",
                **_semantic("B2-contract"),
                "dependencies": ["B1"],
                "required": True,
                "status": "pending",
                "evidence": [],
                "evidence_contract": _visual_contract("B2-contract"),
            },
        ),
        dependency_rewrites={},
        replacement_anchor="B2",
        preserved_node_ids=("A",),
        rationale="replace an unverifiable state with observable boundary states",
    )


def test_valid_patch_preserves_verified_state_and_reconnects_downstream():
    before = _nodes()
    original_a = deepcopy(before["A"])
    after = apply_plan_patch(
        before,
        _patch(),
        EnvironmentCapabilities.screenshot_only(),
        protected_node_ids={"A"},
    )
    assert after["A"] == original_a
    assert "B" not in after
    assert after["C"]["dependencies"] == ["B2"]
    assert after["B1"]["dependencies"] == ["A"]
    assert before == _nodes()


def test_cycle_is_rejected_without_mutating_current_graph():
    before = _nodes()
    snapshot = deepcopy(before)
    patch = _patch()
    cyclic = PlanPatch(
        trigger_node_id=patch.trigger_node_id,
        replace_nodes=patch.replace_nodes,
        new_nodes=patch.new_nodes,
        dependency_rewrites={"A": ("B2",)},
        replacement_anchor=patch.replacement_anchor,
        rationale="invalid cycle",
    )
    result = validate_plan_patch(
        before, cyclic, EnvironmentCapabilities.screenshot_only()
    )
    assert not result.valid
    assert any("cycle" in error for error in result.errors)
    assert before == snapshot


def test_new_node_with_unsupported_source_is_rejected():
    patch = _patch()
    bad_nodes = list(deepcopy(patch.new_nodes))
    bad_nodes[0]["evidence_contract"] = {
        "contract_id": "a11y-only",
        "evidence_type": "structured",
        "sources": ["accessibility_tree"],
        "predicate": {"field": "checked", "operator": "eq", "value": True},
        "success_condition": "checked",
        "allow_mllm_fallback": False,
    }
    invalid = PlanPatch(
        trigger_node_id="B",
        replace_nodes=("B",),
        new_nodes=tuple(bad_nodes),
        dependency_rewrites={},
        replacement_anchor="B2",
        preserved_node_ids=("A",),
    )
    result = validate_plan_patch(
        _nodes(), invalid, EnvironmentCapabilities.screenshot_only()
    )
    assert not result.valid
    assert any("required evidence sources" in error for error in result.errors)


def test_patch_cannot_replace_protected_verified_node():
    patch = PlanPatch(
        trigger_node_id="A",
        replace_nodes=("A",),
        new_nodes=(
            {
                "node_id": "A2",
                **_semantic("A2-contract"),
                "dependencies": [],
                "required": True,
                "evidence_contract": _visual_contract("A2-contract"),
            },
        ),
        dependency_rewrites={},
        replacement_anchor="A2",
        preserved_node_ids=("A",),
    )
    result = validate_plan_patch(
        _nodes(), patch, EnvironmentCapabilities.screenshot_only()
    )
    assert not result.valid
    assert any("protected" in error for error in result.errors)


def test_preserved_downstream_node_may_reconnect_dependencies_only():
    patch = _patch()
    value = patch.to_dict()
    value["preserved_node_ids"] = ["A", "C"]
    result = validate_plan_patch(
        _nodes(), PlanPatch.from_dict(value),
        EnvironmentCapabilities.screenshot_only(), protected_node_ids={"A"},
    )
    assert result.valid
    assert result.patched_nodes["C"]["dependencies"] == ["B2"]


def test_plan_patch_parser_accepts_wrappers_aliases_and_list_rewrites():
    value = _patch().to_dict()
    value["nodes_to_replace"] = value.pop("replace_nodes")
    value["downstream_anchor"] = value.pop("replacement_anchor")
    value["preserved_nodes"] = value.pop("preserved_node_ids")
    value["dependency_rewrites"] = [{"node_id": "C", "dependencies": ["B2"]}]
    parsed = PlanPatch.from_dict({"plan_patch": value})
    assert parsed.replace_nodes == ("B",)
    assert parsed.replacement_anchor == "B2"
    assert parsed.dependency_rewrites == {"C": ("B2",)}


def test_plan_patch_parser_rejects_malformed_list_rewrite():
    value = _patch().to_dict()
    value["dependency_rewrites"] = [{"node_id": "C"}]
    with pytest.raises(ValueError, match="node_id and dependencies"):
        PlanPatch.from_dict(value)


def test_replacement_anchor_cannot_weaken_trigger_semantics():
    before = _nodes()
    before["B"].update(_semantic("original-B"))
    result = validate_plan_patch(
        before, _patch(), EnvironmentCapabilities.screenshot_only())
    assert not result.valid
    assert any("semantic invariant" in error for error in result.errors)
