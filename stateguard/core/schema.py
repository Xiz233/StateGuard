"""Core schemas: NodeStatus, Evidence, TaskNode, ActionProposal, RepairRequest,
FaultType, GuardResult (StateGuard unified output, 指引.txt §7/8/9/14/15/16/19)."""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from ..verification.contracts import EvidenceContract


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXECUTED = "executed"
    VERIFIED = "verified"
    SUSPICIOUS = "suspicious"
    UNVERIFIABLE = "unverifiable"
    FAILED = "failed"
    STALE = "stale"


class SuspicionReason(str, enum.Enum):
    WEAK_CONTRADICTION = "weak_contradiction"
    VERIFICATION_STAGNATION = "verification_stagnation"
    EVIDENCE_CONFLICT = "evidence_conflict"
    EXECUTOR_OVERCLAIM = "executor_overclaim"
    CONTRACT_DRIFT = "contract_drift"
    STATE_DRIFT = "state_drift"


@dataclass(frozen=True)
class SemanticGoal:
    description: str
    invariant: str | dict[str, Any]
    required: bool = True
    role: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "SemanticGoal":
        return cls(**value)

    @property
    def reference(self) -> str:
        return json.dumps(self.invariant, sort_keys=True, separators=(",", ":")) \
            if isinstance(self.invariant, dict) else str(self.invariant)


@dataclass(frozen=True)
class VerificationIntent:
    target_claim: str
    preferred_evidence_types: tuple[str, ...] = ("visual",)
    persistence_required: bool = False
    strength: str = "normal"

    def __post_init__(self):
        if self.strength not in {"weak", "normal", "strong"}:
            raise ValueError(f"invalid verification strength {self.strength!r}")
        object.__setattr__(
            self, "preferred_evidence_types", tuple(self.preferred_evidence_types))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "VerificationIntent":
        return cls(**value)


@dataclass
class Evidence:
    step_id: int
    source: str
    description: str
    confidence: float
    observation_ref: str | None = None
    contract_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        return cls(**d)


@dataclass
class TaskNode:
    node_id: str
    description: str
    device: str | None = None
    app: str | None = None
    dependencies: list[str] = field(default_factory=list)
    expected_result: str = ""
    expected_effect: dict = field(default_factory=dict)  # ponytail: {var: literal|"@param"} checked after action
    verify_action: str | None = None  # ponytail: persistence-mode check (e.g. reopen)
    status: NodeStatus = NodeStatus.PENDING
    evidence: list[Evidence] = field(default_factory=list)
    required: bool = True
    expected_result_semantic: str | None = None
    structured_predicate: dict | None = None
    evidence_mode: Literal["structured", "visual", "persistence", "hybrid"] = "visual"
    evidence_contract: EvidenceContract | None = None
    semantic_goal: SemanticGoal | None = None
    verification_intent: VerificationIntent | None = None
    active_contract_id: str | None = None
    trust_score: float = 1.0
    suspicion_reason: str | None = None
    suspicious_since_step: int | None = None

    def __post_init__(self):
        semantic = self.expected_result_semantic or self.expected_result or self.description
        if self.semantic_goal is None:
            invariant = self.structured_predicate or self.expected_effect or semantic
            self.semantic_goal = SemanticGoal(
                description=semantic, invariant=invariant, required=self.required)
        if self.verification_intent is None:
            self.verification_intent = VerificationIntent(
                target_claim=semantic,
                preferred_evidence_types=(self.evidence_mode,),
                persistence_required=self.evidence_mode == "persistence",
                strength="strong" if self.evidence_mode == "persistence" else "normal",
            )
        if self.active_contract_id is None and self.evidence_contract is not None:
            self.active_contract_id = self.evidence_contract.contract_id

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["evidence_contract"] = (
            self.evidence_contract.to_dict() if self.evidence_contract else None
        )
        d["semantic_goal"] = self.semantic_goal.to_dict() if self.semantic_goal else None
        d["verification_intent"] = (
            self.verification_intent.to_dict() if self.verification_intent else None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TaskNode":
        d = dict(d)
        d["status"] = NodeStatus(d["status"])
        d["evidence"] = [Evidence.from_dict(e) for e in d.get("evidence", [])]
        contract = d.get("evidence_contract")
        if isinstance(contract, dict):
            from ..verification.contracts import AdaptiveEvidenceContract
            d["evidence_contract"] = (
                AdaptiveEvidenceContract.from_dict(contract)
                if "version" in contract else EvidenceContract.from_dict(contract))
        if isinstance(d.get("semantic_goal"), dict):
            d["semantic_goal"] = SemanticGoal.from_dict(d["semantic_goal"])
        if isinstance(d.get("verification_intent"), dict):
            d["verification_intent"] = VerificationIntent.from_dict(
                d["verification_intent"])
        return cls(**d)

@dataclass
class ActionProposal:
    subgoal_id: str
    action: Any  # generic; in synthetic tasks it is Action(name=..., params=...)
    intent: str = ""
    expected_effect: str = ""
    subgoal_done: bool = False
    is_finish: bool = False
    effect_observability: Literal[
        "visual", "structured", "persistence", "none", "auto"
    ] = "auto"

    def to_dict(self) -> dict:
        d = asdict(self)
        if hasattr(self.action, "to_dict"):
            d["action"] = self.action.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ActionProposal":
        return cls(**d)


class FaultType(str, enum.Enum):
    MISSING_SUBGOAL = "missing_subgoal"
    WRONG_TARGET = "wrong_target"
    WRONG_VALUE = "wrong_value"
    WRONG_FORMAT = "wrong_format"
    NOT_PERSISTED = "not_persisted"
    NO_EFFECT = "no_effect"
    DEPENDENCY_VIOLATION = "dependency_violation"
    PREMATURE_FINISH = "premature_finish"


@dataclass
class RepairRequest:
    fault_root: str
    error_type: str
    goal: str
    preserve_nodes: list[str] = field(default_factory=list)
    stale_nodes: list[str] = field(default_factory=list)
    reverify_nodes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    repair_cycle_id: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["error_type"] = self.error_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RepairRequest":
        return cls(**d)

    def remap_nodes(self, replacements: dict[str, str],
                    valid_nodes: set[str] | frozenset[str]) -> "RepairRequest":
        """Retarget a live repair after a local DAG replacement."""
        valid = set(valid_nodes)

        def mapped(node_id: str) -> str:
            return replacements.get(node_id, node_id)

        def mapped_list(node_ids: list[str]) -> list[str]:
            result = []
            for node_id in node_ids:
                target = mapped(node_id)
                if target in valid and target not in result:
                    result.append(target)
            return result

        root = mapped(self.fault_root)
        if root not in valid:
            raise ValueError(f"repair root {self.fault_root!r} has no live replacement")
        reverify = mapped_list(self.reverify_nodes)
        if root not in reverify:
            reverify.insert(0, root)
        return RepairRequest(
            fault_root=root,
            error_type=self.error_type,
            goal=self.goal,
            preserve_nodes=mapped_list(self.preserve_nodes),
            stale_nodes=mapped_list(self.stale_nodes),
            reverify_nodes=reverify,
            confidence=self.confidence,
            repair_cycle_id=self.repair_cycle_id,
        )


@dataclass
class VerificationRequest:
    target: str
    subgoal_id: str
    cycles: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# StateGuard unified output schema (指引.txt §19).
@dataclass
class GuardResult:
    judgement: str  # "verified" | "contradicted" | "unknown"
    progress_updates: list[dict] = field(default_factory=list)
    fault_root: str | None = None
    fault_type: str | None = None
    repair: RepairRequest | None = None
    # internal runtime fields (not part of §19 JSON schema)
    state_updates: list[dict] = field(default_factory=list)
    approved: bool = False
    verification_target: str | None = None
    reason: str = ""
    unknown_reason: str | None = None
    unknown_type: str | None = None
    evidence_gap: dict | None = None
    active_contract_id: str | None = None

    @property
    def requires_repair(self) -> bool:
        return self.judgement == "contradicted"

    def to_dict(self) -> dict:
        unknown_type = self.unknown_type
        if self.judgement == "unknown" and unknown_type is None:
            from ..verification.unknowns import classify_unknown_type
            unknown_type = classify_unknown_type({
                "unknown_reason": self.unknown_reason,
                "verification_target": self.verification_target,
                "reason": self.reason,
                "evidence_gap": self.evidence_gap,
            })
        d = {
            "judgement": self.judgement,
            "progress_updates": self.progress_updates,
            "fault_root": self.fault_root,
            "fault_type": self.fault_type,
            "repair": self.repair.to_dict() if self.repair else None,
            "state_updates": self.state_updates,
            "approved": self.approved,
            "verification_target": self.verification_target,
            "reason": self.reason,
            "unknown_reason": self.unknown_reason,
            "unknown_type": unknown_type,
            "evidence_gap": self.evidence_gap,
            "active_contract_id": self.active_contract_id,
        }
        return d
