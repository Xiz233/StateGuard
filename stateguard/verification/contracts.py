"""Evidence contracts bind semantic task states to real evidence channels."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    VISUAL = "visual"
    STRUCTURED = "structured"
    PERSISTENCE = "persistence"
    HYBRID = "hybrid"


class EvidenceSource(str, Enum):
    SCREENSHOT = "screenshot"
    ACCESSIBILITY_TREE = "accessibility_tree"
    STRUCTURED_STATE = "structured_state"
    APP_STATE = "app_state"
    EXTERNAL_TOOL = "external_tool"
    CLIPBOARD = "clipboard"


class ContractStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    INVALID = "invalid"
    SUPERSEDED = "superseded"
    UNGROUNDABLE = "ungroundable"


class ContractProvenance(str, Enum):
    LEGACY = "legacy"
    PLANNER = "planner"
    GROUNDER = "grounder"
    REGROUNDER = "regrounder"


@dataclass(frozen=True)
class ObservableClaim:
    claim_id: str
    semantic_relation: str
    operator: str
    expected_value: Any
    subject: str | None = None
    ui_anchor: dict[str, Any] | None = None
    source_preference: tuple[EvidenceSource, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(
            self, "source_preference",
            tuple(EvidenceSource(value) for value in self.source_preference))
        object.__setattr__(self, "ui_anchor", deepcopy(self.ui_anchor))

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "semantic_relation": self.semantic_relation,
            "subject": self.subject,
            "operator": self.operator,
            "expected_value": deepcopy(self.expected_value),
            "ui_anchor": deepcopy(self.ui_anchor),
            "source_preference": [value.value for value in self.source_preference],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ObservableClaim":
        return cls(**value)


@dataclass(frozen=True)
class EvidenceContract:
    contract_id: str
    evidence_type: EvidenceType
    sources: tuple[EvidenceSource, ...]
    success_condition: str | dict[str, Any]
    verifier_id: str | None = None
    predicate: dict[str, Any] | None = None
    verify_action: dict[str, Any] | None = None
    observable_fields: tuple[str, ...] = field(default_factory=tuple)
    contradiction_condition: str | dict[str, Any] | None = None
    allow_mllm_fallback: bool = True

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("contract_id must not be empty")
        object.__setattr__(self, "sources", tuple(EvidenceSource(v) for v in self.sources))
        object.__setattr__(self, "observable_fields", tuple(self.observable_fields))
        object.__setattr__(self, "predicate", deepcopy(self.predicate))
        object.__setattr__(self, "verify_action", deepcopy(self.verify_action))
        object.__setattr__(self, "success_condition", deepcopy(self.success_condition))
        object.__setattr__(
            self, "contradiction_condition", deepcopy(self.contradiction_condition)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "evidence_type": self.evidence_type.value,
            "sources": [source.value for source in self.sources],
            "verifier_id": self.verifier_id,
            "predicate": deepcopy(self.predicate),
            "verify_action": deepcopy(self.verify_action),
            "observable_fields": list(self.observable_fields),
            "success_condition": deepcopy(self.success_condition),
            "contradiction_condition": deepcopy(self.contradiction_condition),
            "allow_mllm_fallback": self.allow_mllm_fallback,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceContract":
        return cls(
            contract_id=str(value["contract_id"]),
            evidence_type=EvidenceType(value["evidence_type"]),
            sources=tuple(EvidenceSource(v) for v in value.get("sources", ())),
            verifier_id=value.get("verifier_id"),
            predicate=value.get("predicate"),
            verify_action=value.get("verify_action"),
            observable_fields=tuple(value.get("observable_fields", ())),
            success_condition=value.get("success_condition", ""),
            contradiction_condition=value.get("contradiction_condition"),
            allow_mllm_fallback=bool(value.get("allow_mllm_fallback", True)),
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        node_id: str,
        evidence_mode: str,
        success_condition: str | dict[str, Any],
        structured_predicate: dict[str, Any] | None = None,
        expected_effect: dict[str, Any] | None = None,
        verify_action: str | dict[str, Any] | None = None,
    ) -> "EvidenceContract":
        """Create a conservative contract while legacy task files are migrated."""
        evidence_type = EvidenceType(evidence_mode)
        source_map = {
            EvidenceType.VISUAL: (EvidenceSource.SCREENSHOT,),
            EvidenceType.STRUCTURED: (EvidenceSource.STRUCTURED_STATE,),
            EvidenceType.PERSISTENCE: (EvidenceSource.EXTERNAL_TOOL,),
            EvidenceType.HYBRID: (
                EvidenceSource.SCREENSHOT,
                EvidenceSource.STRUCTURED_STATE,
            ),
        }
        return cls(
            contract_id=f"legacy:{node_id}",
            evidence_type=evidence_type,
            sources=source_map[evidence_type],
            predicate=deepcopy(structured_predicate or expected_effect) or None,
            verify_action=deepcopy(verify_action),
            success_condition=deepcopy(success_condition),
        )


@dataclass(frozen=True)
class AdaptiveEvidenceContract(EvidenceContract):
    node_id: str = ""
    version: int = 1
    semantic_goal_ref: str = ""
    grounded_at_step: int = 0
    context_signature: dict[str, Any] = field(default_factory=dict)
    observable_claims: tuple[ObservableClaim, ...] = field(default_factory=tuple)
    verifier_candidates: tuple[str, ...] = field(default_factory=tuple)
    preferred_verifier: str | None = None
    fallback_strategy: str | None = None
    confidence: float | None = None
    provenance: ContractProvenance = ContractProvenance.GROUNDER
    status: ContractStatus = ContractStatus.ACTIVE

    def __post_init__(self):
        super().__post_init__()
        if self.version < 1:
            raise ValueError("contract version must be positive")
        object.__setattr__(self, "context_signature", deepcopy(self.context_signature))
        object.__setattr__(
            self, "observable_claims",
            tuple(claim if isinstance(claim, ObservableClaim)
                  else ObservableClaim.from_dict(claim)
                  for claim in self.observable_claims))
        object.__setattr__(self, "verifier_candidates", tuple(self.verifier_candidates))
        object.__setattr__(self, "provenance", ContractProvenance(self.provenance))
        object.__setattr__(self, "status", ContractStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        value = super().to_dict()
        value.update({
            "node_id": self.node_id,
            "version": self.version,
            "semantic_goal_ref": self.semantic_goal_ref,
            "grounded_at_step": self.grounded_at_step,
            "context_signature": deepcopy(self.context_signature),
            "observable_claims": [claim.to_dict() for claim in self.observable_claims],
            "verifier_candidates": list(self.verifier_candidates),
            "preferred_verifier": self.preferred_verifier,
            "fallback_strategy": self.fallback_strategy,
            "confidence": self.confidence,
            "provenance": self.provenance.value,
            "status": self.status.value,
        })
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AdaptiveEvidenceContract":
        return cls(
            contract_id=str(value["contract_id"]),
            evidence_type=EvidenceType(value["evidence_type"]),
            sources=tuple(EvidenceSource(item) for item in value.get("sources", ())),
            success_condition=value.get("success_condition", ""),
            verifier_id=value.get("verifier_id"),
            predicate=value.get("predicate"),
            verify_action=value.get("verify_action"),
            observable_fields=tuple(value.get("observable_fields", ())),
            contradiction_condition=value.get("contradiction_condition"),
            allow_mllm_fallback=bool(value.get("allow_mllm_fallback", True)),
            node_id=str(value.get("node_id", "")),
            version=int(value.get("version", 1)),
            semantic_goal_ref=str(value.get("semantic_goal_ref", "")),
            grounded_at_step=int(value.get("grounded_at_step", 0)),
            context_signature=value.get("context_signature", {}),
            observable_claims=tuple(value.get("observable_claims", ())),
            verifier_candidates=tuple(value.get("verifier_candidates", ())),
            preferred_verifier=value.get("preferred_verifier"),
            fallback_strategy=value.get("fallback_strategy"),
            confidence=value.get("confidence"),
            provenance=value.get("provenance", ContractProvenance.GROUNDER.value),
            status=value.get("status", ContractStatus.ACTIVE.value),
        )
