from stateguard.environment import EnvironmentCapabilities
from stateguard.verification import (
    EvidenceContract,
    EvidenceSource,
    EvidenceType,
)
from stateguard.verification.validator import validate_task_graph
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import TaskNode


def _node(contract, node_id="S1"):
    return {"node_id": node_id, "required": True, "evidence_contract": contract}


def test_contract_round_trip_does_not_alias_mutable_values():
    predicate = {"field": "volume", "operator": "eq", "value": 50}
    contract = EvidenceContract(
        contract_id="volume-50",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.STRUCTURED_STATE,),
        predicate=predicate,
        success_condition={"volume": 50},
        allow_mllm_fallback=False,
    )
    predicate["value"] = 0
    restored = EvidenceContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.predicate["value"] == 50


def test_visual_contract_passes_in_screenshot_environment():
    contract = EvidenceContract(
        contract_id="checkbox-checked",
        evidence_type=EvidenceType.VISUAL,
        sources=(EvidenceSource.SCREENSHOT,),
        success_condition="The checkbox is visibly checked.",
    )
    result = validate_task_graph([_node(contract)], EnvironmentCapabilities.screenshot_only())
    assert result.valid


def test_structured_contract_passes_with_predicate_and_source():
    contract = EvidenceContract(
        contract_id="volume-50",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.STRUCTURED_STATE,),
        predicate={"field": "volume", "operator": "eq", "value": 50},
        success_condition={"volume": 50},
        allow_mllm_fallback=False,
    )
    capabilities = EnvironmentCapabilities(
        available_sources=frozenset({EvidenceSource.STRUCTURED_STATE})
    )
    assert validate_task_graph([_node(contract)], capabilities).valid


def test_optional_visual_fallback_does_not_require_screenshot_when_primary_exists():
    contract = EvidenceContract(
        contract_id="volume-50",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.STRUCTURED_STATE,),
        predicate={"field": "volume", "operator": "eq", "value": 50},
        success_condition={"volume": 50},
        allow_mllm_fallback=True,
    )
    capabilities = EnvironmentCapabilities(
        available_sources=frozenset({EvidenceSource.STRUCTURED_STATE})
    )
    assert validate_task_graph([_node(contract)], capabilities).valid


def test_persistence_contract_passes_with_external_verifier():
    contract = EvidenceContract(
        contract_id="file-exists",
        evidence_type=EvidenceType.PERSISTENCE,
        sources=(EvidenceSource.EXTERNAL_TOOL,),
        verifier_id="file_exists",
        success_condition={"path": "/tmp/result.txt", "exists": True},
        allow_mllm_fallback=False,
    )
    capabilities = EnvironmentCapabilities(
        available_sources=frozenset({EvidenceSource.EXTERNAL_TOOL}),
        supported_verifiers=frozenset({"file_exists"}),
    )
    assert validate_task_graph([_node(contract)], capabilities).valid


def test_unverifiable_structured_state_is_rejected_without_keyword_rules():
    contract = EvidenceContract(
        contract_id="private-result",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.STRUCTURED_STATE,),
        success_condition="An internal result exists.",
        allow_mllm_fallback=False,
    )
    capabilities = EnvironmentCapabilities(
        available_sources=frozenset({EvidenceSource.STRUCTURED_STATE})
    )
    result = validate_task_graph([_node(contract)], capabilities)
    assert not result.valid
    assert "predicate or structured verifier" in result.invalid_nodes[0].reason


def test_missing_source_is_reported():
    contract = EvidenceContract(
        contract_id="selected-element",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.ACCESSIBILITY_TREE,),
        predicate={"field": "selected", "operator": "eq", "value": True},
        success_condition="The element is selected.",
        allow_mllm_fallback=False,
    )
    result = validate_task_graph([_node(contract)], EnvironmentCapabilities.screenshot_only())
    assert not result.valid
    assert result.invalid_nodes[0].missing_sources == (
        EvidenceSource.ACCESSIBILITY_TREE,
    )


def test_optional_node_without_contract_does_not_fail_preflight():
    node = {"node_id": "S1", "required": False, "evidence_contract": None}
    assert validate_task_graph([node], EnvironmentCapabilities.screenshot_only()).valid


def test_task_node_contract_round_trip():
    contract = EvidenceContract(
        contract_id="visible-title",
        evidence_type=EvidenceType.VISUAL,
        sources=(EvidenceSource.SCREENSHOT,),
        success_condition="The expected title is visible.",
    )
    node = TaskNode("S1", "show title", evidence_contract=contract)
    assert TaskNode.from_dict(node.to_dict()).evidence_contract == contract


def test_legacy_task_compiler_builds_evidence_contract():
    state = compile_from_spec({
        "nodes": [{
            "node_id": "S1",
            "description": "set volume",
            "dependencies": [],
            "expected_result": "volume == 50",
            "expected_effect": {"volume": 50},
            "evidence_mode": "structured",
            "required": True,
        }]
    })
    contract = state.get("S1").evidence_contract
    assert contract.contract_id == "legacy:S1"
    assert contract.predicate == {"volume": 50}
