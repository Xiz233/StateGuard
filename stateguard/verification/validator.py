"""Preflight validation for evidence contracts on required task nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from ..environment.capabilities import EnvironmentCapabilities
from .contracts import (
    AdaptiveEvidenceContract, EvidenceContract, EvidenceSource, EvidenceType,
)


class VerifierLookup(Protocol):
    def contains(self, verifier_id: str) -> bool: ...


@dataclass(frozen=True)
class InvalidContract:
    node_id: str
    reason: str
    missing_sources: tuple[EvidenceSource, ...] = field(default_factory=tuple)
    missing_verifier: str | None = None
    suggested_evidence_types: tuple[EvidenceType, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContractValidationResult:
    invalid_nodes: tuple[InvalidContract, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        return not self.invalid_nodes


@dataclass(frozen=True)
class AdaptiveContractValidationResult:
    valid: bool
    semantic_preserved: bool
    no_weakening: bool
    evidence_available: bool
    verifier_available: bool
    rejection_reason: str | None = None


def validate_contract(node: Any, old_contract: AdaptiveEvidenceContract | None,
                      new_contract: AdaptiveEvidenceContract,
                      capabilities: EnvironmentCapabilities,
                      verifier_registry: VerifierLookup | None = None,
                      require_available_source: bool = True) \
        -> AdaptiveContractValidationResult:
    """Validate a grounded contract without interpreting task-specific language."""
    goal = _field(node, "semantic_goal")
    goal_ref = getattr(goal, "reference", "")
    invariant = getattr(goal, "invariant", None)
    semantic_preserved = bool(goal_ref and new_contract.semantic_goal_ref == goal_ref)
    if old_contract is not None:
        semantic_preserved = semantic_preserved and (
            old_contract.semantic_goal_ref == new_contract.semantic_goal_ref
            and new_contract.version == old_contract.version + 1)

    no_weakening = (
        new_contract.success_condition == invariant
        and bool(new_contract.observable_claims)
        and all(_claim_preserves_invariant(claim, invariant, _field(node, "node_id", ""))
                for claim in new_contract.observable_claims)
    )
    evidence_available = bool(new_contract.sources) and (
        capabilities.has_sources(new_contract.sources) if require_available_source else True)
    requested = tuple(filter(None, (
        new_contract.preferred_verifier, new_contract.verifier_id,
        *new_contract.verifier_candidates)))
    verifier_available = bool(requested) and any(
        verifier_registry.contains(verifier_id) if verifier_registry is not None
        else capabilities.supports_verifier(verifier_id)
        for verifier_id in requested)

    reasons = []
    if not semantic_preserved:
        reasons.append("semantic goal reference changed")
    if not no_weakening:
        reasons.append("observable claims weaken or replace the semantic invariant")
    if not evidence_available:
        reasons.append("required evidence source is unavailable")
    if not verifier_available:
        reasons.append("no requested verifier is available")
    return AdaptiveContractValidationResult(
        valid=not reasons,
        semantic_preserved=semantic_preserved,
        no_weakening=no_weakening,
        evidence_available=evidence_available,
        verifier_available=verifier_available,
        rejection_reason="; ".join(reasons) or None,
    )


def _claim_preserves_invariant(claim, invariant, node_id: str) -> bool:
    if isinstance(invariant, dict) and {"relation", "operator", "value"} <= invariant.keys():
        return (
            claim.semantic_relation == str(invariant["relation"])
            and claim.operator == str(invariant["operator"])
            and claim.expected_value == invariant["value"]
            and claim.subject == invariant.get("subject")
        )
    return (
        claim.semantic_relation == f"semantic_goal:{node_id}"
        and claim.operator == "satisfies"
        and claim.expected_value == invariant
    )


def validate_task_graph(
    nodes: Iterable[Any],
    capabilities: EnvironmentCapabilities,
    verifier_registry: VerifierLookup | None = None,
) -> ContractValidationResult:
    invalid: list[InvalidContract] = []
    for node in nodes:
        if not bool(_field(node, "required", True)):
            continue
        node_id = str(_field(node, "node_id", "<unknown>"))
        contract = _field(node, "evidence_contract")
        if contract is None:
            invalid.append(InvalidContract(node_id, "required node has no evidence contract"))
            continue
        if isinstance(contract, dict):
            try:
                contract = EvidenceContract.from_dict(contract)
            except (KeyError, TypeError, ValueError) as exc:
                invalid.append(InvalidContract(node_id, f"invalid evidence contract: {exc}"))
                continue
        if not isinstance(contract, EvidenceContract):
            invalid.append(InvalidContract(node_id, "unsupported evidence contract value"))
            continue
        invalid.extend(
            _validate_contract(node_id, contract, capabilities, verifier_registry)
        )
    return ContractValidationResult(tuple(invalid))


def _validate_contract(
    node_id: str,
    contract: EvidenceContract,
    capabilities: EnvironmentCapabilities,
    registry: VerifierLookup | None,
) -> list[InvalidContract]:
    problems: list[InvalidContract] = []
    if not contract.sources:
        problems.append(InvalidContract(node_id, "evidence contract has no sources"))
    else:
        missing = tuple(sorted(capabilities.missing_sources(contract.sources), key=str))
        if missing:
            problems.append(
                InvalidContract(
                    node_id,
                    "environment does not provide all required evidence sources",
                    missing_sources=missing,
                    suggested_evidence_types=_suggestions(capabilities),
                )
            )

    if not contract.success_condition:
        problems.append(InvalidContract(node_id, "success condition is empty"))

    if contract.verifier_id:
        registered = (
            registry.contains(contract.verifier_id)
            if registry is not None
            else capabilities.supports_verifier(contract.verifier_id)
        )
        if not registered:
            problems.append(
                InvalidContract(
                    node_id,
                    "contract verifier is not registered",
                    missing_verifier=contract.verifier_id,
                )
            )

    if contract.evidence_type == EvidenceType.STRUCTURED:
        has_structured_verifier = bool(contract.verifier_id)
        if contract.predicate is None and not has_structured_verifier:
            problems.append(
                InvalidContract(
                    node_id,
                    "structured contract needs a predicate or structured verifier",
                    suggested_evidence_types=_suggestions(capabilities),
                )
            )

    if contract.evidence_type == EvidenceType.PERSISTENCE:
        if contract.verify_action is None and not contract.verifier_id:
            problems.append(
                InvalidContract(
                    node_id,
                    "persistence contract needs a verify action or persistence verifier",
                    suggested_evidence_types=_suggestions(capabilities),
                )
            )

    has_primary_verification_path = bool(
        contract.verifier_id or contract.predicate or contract.verify_action
    )
    if contract.allow_mllm_fallback and not has_primary_verification_path:
        if EvidenceSource.SCREENSHOT not in capabilities.available_sources:
            problems.append(
                InvalidContract(
                    node_id,
                    "MLLM fallback requested but screenshot evidence is unavailable",
                    missing_sources=(EvidenceSource.SCREENSHOT,),
                )
            )
    return problems


def _suggestions(capabilities: EnvironmentCapabilities) -> tuple[EvidenceType, ...]:
    values: list[EvidenceType] = []
    if EvidenceSource.SCREENSHOT in capabilities.available_sources:
        values.append(EvidenceType.VISUAL)
    if {
        EvidenceSource.STRUCTURED_STATE,
        EvidenceSource.APP_STATE,
    } & capabilities.available_sources:
        values.append(EvidenceType.STRUCTURED)
    if EvidenceSource.EXTERNAL_TOOL in capabilities.available_sources:
        values.append(EvidenceType.PERSISTENCE)
    return tuple(values)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
