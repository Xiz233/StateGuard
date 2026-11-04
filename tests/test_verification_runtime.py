from stateguard.core.observability import CapabilityResolver
from stateguard.environment import EnvironmentCapabilities
from stateguard.runtime.verification_debt import (
    DebtAction,
    VerificationDebtConfig,
    VerificationDebtTracker,
)
from stateguard.verification import EvidenceContract, EvidenceSource, EvidenceType
from stateguard.verification.observation import ObservationBundle
from stateguard.verification.registry import default_registry
from stateguard.verification.result import EvidenceResult, EvidenceStrategy


def _structured_contract():
    return EvidenceContract(
        contract_id="setting-volume",
        evidence_type=EvidenceType.STRUCTURED,
        sources=(EvidenceSource.STRUCTURED_STATE,),
        predicate={"field": "volume", "operator": "eq", "value": 50},
        success_condition={"volume": 50},
        allow_mllm_fallback=False,
    )


def test_structured_predicate_verifier_reads_bundle():
    contract = _structured_contract()
    capabilities = EnvironmentCapabilities(
        available_sources=frozenset({EvidenceSource.STRUCTURED_STATE})
    )
    registry = default_registry()
    verifier = registry.get("structured_predicate")
    assert verifier.supports(contract, capabilities)
    result = verifier.verify(contract, ObservationBundle(structured_state={"volume": 50}))
    assert result.judgement.value == "verified"


def test_executor_observability_claim_cannot_override_capabilities():
    contract = _structured_contract()
    resolved = CapabilityResolver.resolve(
        {"type": "click"},
        contract,
        EnvironmentCapabilities.screenshot_only(),
        default_registry(),
        declared_hint="structured",
    )
    assert resolved.declared_hint == "structured"
    assert not resolved.directly_observable
    assert EvidenceSource.STRUCTURED_STATE not in resolved.sources


def test_different_actions_do_not_reset_node_contract_debt():
    contract = _structured_contract()
    tracker = VerificationDebtTracker(
        VerificationDebtConfig(soft_threshold=2, strategy_switch_threshold=3, hard_threshold=5)
    )
    actions = ["click", "scroll", "hotkey"]
    update = None
    for step, _action in enumerate(actions, 1):
        result = EvidenceResult.unknown(
            "structured_predicate",
            target="observe volume",
            strategy=EvidenceStrategy.ACQUIRE_STRUCTURED_EVIDENCE,
        )
        update = tracker.update("S1", contract, result, step)
    assert update.state.consecutive_unknown == 3
    assert update.state.no_new_evidence_count == 3
    assert update.action == DebtAction.REGROUND_CONTRACT


def test_new_contract_relevant_value_records_information_gain():
    contract = _structured_contract()
    tracker = VerificationDebtTracker(VerificationDebtConfig(2, 3, 5))
    first = EvidenceResult.unknown(
        "structured_predicate",
        target="observe volume",
        relevant_values={"volume": None},
    )
    second = EvidenceResult.unknown(
        "structured_predicate",
        target="observe volume",
        relevant_values={"volume": 40},
    )
    tracker.update("S1", contract, first, 1)
    update = tracker.update("S1", contract, second, 2)
    assert update.information_gain
    assert update.state.no_new_evidence_count == 0
    assert update.state.last_progress_step == 2


def test_hard_debt_marks_contract_path_unverifiable_not_failed():
    contract = _structured_contract()
    tracker = VerificationDebtTracker(VerificationDebtConfig(1, 2, 3))
    update = None
    for step in range(1, 4):
        update = tracker.update(
            "S1",
            contract,
            EvidenceResult.unknown("structured_predicate", target="observe volume"),
            step,
        )
    assert update.action == DebtAction.UNVERIFIABLE
    assert update.state.debt_score == 3
