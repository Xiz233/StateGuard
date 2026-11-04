"""Verifier protocol, registry, and benchmark-neutral built-in verifiers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..environment.capabilities import EnvironmentCapabilities
from .contracts import EvidenceContract, EvidenceSource, EvidenceType
from .observation import ObservationBundle
from .result import EvidenceJudgement, EvidenceResult


class Verifier(Protocol):
    verifier_id: str

    def supports(
        self, contract: EvidenceContract, capabilities: EnvironmentCapabilities
    ) -> bool: ...

    def verify(
        self, contract: EvidenceContract, observation: ObservationBundle
    ) -> EvidenceResult: ...


class VerifierRegistry:
    def __init__(self) -> None:
        self._verifiers: dict[str, Verifier] = {}

    def register(self, verifier: Verifier) -> None:
        if verifier.verifier_id in self._verifiers:
            raise ValueError(f"verifier {verifier.verifier_id!r} is already registered")
        self._verifiers[verifier.verifier_id] = verifier

    def contains(self, verifier_id: str) -> bool:
        return verifier_id in self._verifiers

    def get(self, verifier_id: str) -> Verifier:
        return self._verifiers[verifier_id]

    def candidates(
        self, contract: EvidenceContract, capabilities: EnvironmentCapabilities
    ) -> tuple[str, ...]:
        if contract.verifier_id:
            verifier = self._verifiers.get(contract.verifier_id)
            return (
                (contract.verifier_id,)
                if verifier is not None and verifier.supports(contract, capabilities)
                else ()
            )
        return tuple(
            verifier_id
            for verifier_id, verifier in self._verifiers.items()
            if verifier.supports(contract, capabilities)
        )


class StructuredPredicateVerifier:
    verifier_id = "structured_predicate"

    def supports(self, contract, capabilities) -> bool:
        return (
            contract.evidence_type in {EvidenceType.STRUCTURED, EvidenceType.HYBRID}
            and contract.predicate is not None
            and bool(
                {
                    EvidenceSource.STRUCTURED_STATE,
                    EvidenceSource.APP_STATE,
                }
                & capabilities.available_sources
            )
        )

    def verify(self, contract, observation) -> EvidenceResult:
        source, state = _first_value(
            observation,
            (EvidenceSource.STRUCTURED_STATE, EvidenceSource.APP_STATE),
        )
        return _predicate_result(self.verifier_id, source, state, contract.predicate)


class AccessibilityVerifier:
    verifier_id = "accessibility_predicate"

    def supports(self, contract, capabilities) -> bool:
        return (
            EvidenceSource.ACCESSIBILITY_TREE in contract.sources
            and EvidenceSource.ACCESSIBILITY_TREE in capabilities.available_sources
            and contract.predicate is not None
        )

    def verify(self, contract, observation) -> EvidenceResult:
        return _predicate_result(
            self.verifier_id,
            EvidenceSource.ACCESSIBILITY_TREE,
            observation.accessibility_tree,
            contract.predicate,
        )


class PersistenceVerifier:
    verifier_id = "persistence"

    def supports(self, contract, capabilities) -> bool:
        return (
            contract.evidence_type in {EvidenceType.PERSISTENCE, EvidenceType.HYBRID}
            and EvidenceSource.EXTERNAL_TOOL in capabilities.available_sources
            and (contract.predicate is not None or contract.verify_action is not None)
        )

    def verify(self, contract, observation) -> EvidenceResult:
        predicate = contract.predicate or contract.success_condition
        return _predicate_result(
            self.verifier_id,
            EvidenceSource.EXTERNAL_TOOL,
            observation.external_state,
            predicate if isinstance(predicate, dict) else None,
        )


class VisualMLLMVerifier:
    verifier_id = "visual_mllm"

    def __init__(
        self,
        callback: Callable[[EvidenceContract, ObservationBundle], EvidenceResult],
    ) -> None:
        self._callback = callback

    def supports(self, contract, capabilities) -> bool:
        return (
            contract.allow_mllm_fallback
            and EvidenceSource.SCREENSHOT in capabilities.available_sources
        )

    def verify(self, contract, observation) -> EvidenceResult:
        return self._callback(contract, observation)


def default_registry(visual_callback=None) -> VerifierRegistry:
    registry = VerifierRegistry()
    registry.register(StructuredPredicateVerifier())
    registry.register(AccessibilityVerifier())
    registry.register(PersistenceVerifier())
    if visual_callback is not None:
        registry.register(VisualMLLMVerifier(visual_callback))
    return registry


def _first_value(observation, sources):
    for source in sources:
        value = observation.value_for_source(source.value)
        if value is not None:
            return source, value
    return sources[0], None


def _predicate_result(verifier_id, source, state, predicate) -> EvidenceResult:
    if state is None or not isinstance(predicate, dict):
        return EvidenceResult.unknown(
            verifier_id,
            sources=(source,),
            reason="required predicate evidence is unavailable",
        )
    field = predicate.get("field")
    operator = predicate.get("operator", "eq")
    expected = predicate.get("value")
    found, actual = _resolve_field(state, field)
    relevant = {str(field): actual} if found else {}
    if not found:
        return EvidenceResult.unknown(
            verifier_id,
            sources=(source,),
            target=f"observe field {field}",
            reason="predicate field is absent",
            relevant_values=relevant,
        )
    matched = _compare(actual, operator, expected)
    return EvidenceResult(
        EvidenceJudgement.VERIFIED if matched else EvidenceJudgement.CONTRADICTED,
        verifier_id,
        (source,),
        relevant,
        reason=f"predicate {field} {operator} {expected!r} evaluated against {actual!r}",
        progress_evidence=True,
    )


def _resolve_field(state: Any, field: Any) -> tuple[bool, Any]:
    if field in (None, ""):
        return True, state
    current = state
    for part in str(field).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "contains":
        return expected in actual
    if operator == "exists":
        return actual is not None
    if operator == "truthy":
        return bool(actual)
    raise ValueError(f"unsupported predicate operator {operator!r}")
