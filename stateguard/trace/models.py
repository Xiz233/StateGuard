from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExecutionTraceEntry:
    step_id: int
    active_node_id: str
    executor_intent: str
    action: Any
    expected_effect: str
    effect_observability: str = "auto"
    proposed_action: Any = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observation_before_summary: dict = field(default_factory=dict)
    observation_after_summary: dict = field(default_factory=dict)
    state_before: dict = field(default_factory=dict)
    state_after: dict = field(default_factory=dict)
    checkpoint_reason: str | None = None
    checkpoint_kind: str | None = None
    trust_snapshot: dict[str, float] = field(default_factory=dict)
    execution_phase: str = "normal"
    declared_observability: str | None = None
    resolved_observability: dict | None = None
    active_contract_id: str | None = None
    contract_version: int | None = None
    contract_trigger: str | None = None
    evidence_sources_available: tuple[str, ...] = field(default_factory=tuple)
    evidence_sources_used: tuple[str, ...] = field(default_factory=tuple)
    information_gain: bool = False
    unknown_reason: str | None = None
    verification_debt: int = 0
    verifier_id: str | None = None
    guard_judgement: str | None = None
    subgoal_done: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ExecutionTraceEntry":
        return cls(**value)
