"""Normalized verifier output, including structured UNKNOWN evidence gaps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .contracts import EvidenceSource


class EvidenceJudgement(str, Enum):
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    CONTRADICTED = "contradicted"


class UnknownReason(str, Enum):
    NEED_MORE_EVIDENCE = "need_more_evidence"
    CONTRACT_STALE = "contract_stale"
    SOURCE_UNAVAILABLE = "source_unavailable"
    VERIFIER_INCONCLUSIVE = "verifier_inconclusive"
    NODE_UNVERIFIABLE = "node_unverifiable"


class EvidenceStrategy(str, Enum):
    ACQUIRE_VISUAL_EVIDENCE = "acquire_visual_evidence"
    ACQUIRE_ACCESSIBILITY_EVIDENCE = "acquire_accessibility_evidence"
    ACQUIRE_STRUCTURED_EVIDENCE = "acquire_structured_evidence"
    PERSISTENCE_RECHECK = "persistence_recheck"
    NAVIGATE_TO_OBSERVABLE_STATE = "navigate_to_observable_state"
    EXTERNAL_STATE_QUERY = "external_state_query"


@dataclass(frozen=True)
class EvidenceGap:
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    available_evidence: tuple[str, ...] = field(default_factory=tuple)
    unavailable_evidence: tuple[str, ...] = field(default_factory=tuple)
    attempted_strategy: EvidenceStrategy | None = None
    recommended_strategy: EvidenceStrategy | None = None
    requires_new_source: bool = False
    same_contract: bool = True


@dataclass(frozen=True)
class EvidenceResult:
    judgement: EvidenceJudgement
    verifier_id: str
    sources: tuple[EvidenceSource, ...] = field(default_factory=tuple)
    relevant_values: dict[str, Any] = field(default_factory=dict)
    verification_target: str | None = None
    reason: str = ""
    progress_evidence: bool = False
    strategy: EvidenceStrategy | None = None
    gap: EvidenceGap | None = None
    unknown_reason: UnknownReason | None = None
    active_contract_id: str | None = None

    @classmethod
    def unknown(
        cls,
        verifier_id: str,
        *,
        sources: tuple[EvidenceSource, ...] = (),
        target: str | None = None,
        reason: str = "",
        relevant_values: dict[str, Any] | None = None,
        strategy: EvidenceStrategy | None = None,
        gap: EvidenceGap | None = None,
        unknown_reason: UnknownReason = UnknownReason.NEED_MORE_EVIDENCE,
        active_contract_id: str | None = None,
    ) -> "EvidenceResult":
        return cls(
            EvidenceJudgement.UNKNOWN,
            verifier_id,
            sources,
            relevant_values or {},
            target,
            reason,
            False,
            strategy,
            gap,
            unknown_reason,
            active_contract_id,
        )
