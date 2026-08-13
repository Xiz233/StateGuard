"""Core schemas: NodeStatus, Evidence, TaskNode, ActionProposal, RepairRequest,
FaultType, GuardResult (StateGuard unified output, 指引.txt §7/8/9/14/15/16/19)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Any


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXECUTED = "executed"
    VERIFIED = "verified"
    FAILED = "failed"
    STALE = "stale"


@dataclass
class Evidence:
    step_id: int
    source: str
    description: str
    confidence: float
    observation_ref: str | None = None

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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TaskNode":
        d = dict(d)
        d["status"] = NodeStatus(d["status"])
        d["evidence"] = [Evidence.from_dict(e) for e in d.get("evidence", [])]
        return cls(**d)

@dataclass
class ActionProposal:
    subgoal_id: str
    action: Any  # generic; in synthetic tasks it is Action(name=..., params=...)
    intent: str = ""
    expected_effect: str = ""
    is_finish: bool = False

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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["error_type"] = self.error_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RepairRequest":
        return cls(**d)


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

    @property
    def requires_repair(self) -> bool:
        return self.judgement == "contradicted"

    def to_dict(self) -> dict:
        d = {
            "judgement": self.judgement,
            "progress_updates": self.progress_updates,
            "fault_root": self.fault_root,
            "fault_type": self.fault_type,
            "repair": self.repair.to_dict() if self.repair else None,
            "state_updates": self.state_updates,
            "approved": self.approved,
            "verification_target": self.verification_target,
        }
        return d
