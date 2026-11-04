"""Resolve runtime observability from contracts and environment capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from ..environment.capabilities import EnvironmentCapabilities
from ..verification.contracts import EvidenceContract, EvidenceSource
from ..verification.registry import VerifierRegistry


@dataclass(frozen=True)
class ResolvedObservability:
    sources: tuple[EvidenceSource, ...]
    verifier_candidates: tuple[str, ...]
    directly_observable: bool
    reason: str
    declared_hint: str | None = None


class CapabilityResolver:
    @staticmethod
    def resolve(
        action: dict,
        contract: EvidenceContract,
        capabilities: EnvironmentCapabilities,
        registry: VerifierRegistry,
        declared_hint: str | None = None,
    ) -> ResolvedObservability:
        usable = tuple(
            source for source in contract.sources if source in capabilities.available_sources
        )
        action_type = str(action.get("type", "")) if isinstance(action, dict) else ""
        action_sources = capabilities.sources_for_action(action_type)
        candidates = registry.candidates(contract, capabilities)
        directly_observable = bool(usable and candidates)
        if not usable:
            reason = "contract evidence sources are unavailable"
        elif not candidates:
            reason = "no registered verifier supports the available contract sources"
        elif action_sources and not (set(usable) & action_sources):
            reason = "action has no declared effect channel for the contract sources"
            directly_observable = False
        else:
            reason = "contract, environment, and verifier capabilities agree"
        return ResolvedObservability(
            usable, candidates, directly_observable, reason, declared_hint
        )
