"""Node/contract-level convergence for repeated inconclusive verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..verification.contracts import EvidenceContract
from ..verification.evidence_signature import (
    EvidenceSignature,
    build_evidence_signature,
    has_information_gain,
)
from ..verification.result import EvidenceJudgement, EvidenceResult


class DebtAction(str, Enum):
    NORMAL = "normal"
    MARK_SUSPICIOUS = "mark_suspicious"
    REGROUND_CONTRACT = "reground_contract"
    SWITCH_STRATEGY = "switch_strategy"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class VerificationDebtConfig:
    soft_threshold: int = 2
    strategy_switch_threshold: int = 3
    hard_threshold: int = 5

    def __post_init__(self) -> None:
        if not (0 < self.soft_threshold <= self.strategy_switch_threshold <= self.hard_threshold):
            raise ValueError("verification debt thresholds must be positive and ordered")


@dataclass
class VerificationDebtState:
    node_id: str
    contract_id: str
    consecutive_unknown: int = 0
    no_new_evidence_count: int = 0
    repeated_target_count: int = 0
    repeated_contract_count: int = 0
    grounding_attempts: int = 0
    verifier_switch_count: int = 0
    current_contract_id: str | None = None
    attempted_verifiers: set[str] = field(default_factory=set)
    attempted_sources: set[str] = field(default_factory=set)
    attempted_strategy_ids: set[str] = field(default_factory=set)
    last_evidence_signature: EvidenceSignature | None = None
    last_progress_step: int | None = None
    debt_score: int = 0

    def reset(self, signature: EvidenceSignature | None = None, step: int | None = None) -> None:
        self.consecutive_unknown = 0
        self.no_new_evidence_count = 0
        self.repeated_target_count = 0
        self.debt_score = 0
        self.last_evidence_signature = signature
        self.last_progress_step = step


@dataclass(frozen=True)
class DebtUpdate:
    action: DebtAction
    state: VerificationDebtState
    information_gain: bool


class VerificationDebtTracker:
    def __init__(self, config: VerificationDebtConfig | None = None) -> None:
        self.config = config or VerificationDebtConfig()
        self._states: dict[tuple[str, str], VerificationDebtState] = {}

    def state_for(self, node_id: str, semantic_key: str) -> VerificationDebtState:
        key = (node_id, semantic_key)
        if key not in self._states:
            self._states[key] = VerificationDebtState(node_id, semantic_key)
        return self._states[key]

    def remap_node(self, old_node_id: str, new_node_id: str) -> None:
        """Carry source memory to a replacement while resetting convergence debt."""
        for key, state in list(self._states.items()):
            node_id, semantic_key = key
            if node_id != old_node_id:
                continue
            del self._states[key]
            state.node_id = new_node_id
            state.current_contract_id = None
            state.consecutive_unknown = 0
            state.no_new_evidence_count = 0
            state.repeated_target_count = 0
            state.repeated_contract_count = 0
            state.grounding_attempts = 0
            state.last_evidence_signature = None
            state.last_progress_step = None
            state.debt_score = 0
            target = (new_node_id, semantic_key)
            existing = self._states.get(target)
            if existing is None:
                self._states[target] = state
            else:
                existing.attempted_verifiers.update(state.attempted_verifiers)
                existing.attempted_sources.update(state.attempted_sources)
                existing.attempted_strategy_ids.update(state.attempted_strategy_ids)

    def update(
        self,
        node_id: str,
        contract: EvidenceContract,
        result: EvidenceResult,
        step: int,
    ) -> DebtUpdate:
        semantic_key = getattr(contract, "semantic_goal_ref", "") or contract.contract_id
        state = self.state_for(node_id, semantic_key)
        if state.current_contract_id == contract.contract_id:
            state.repeated_contract_count += 1
        else:
            state.current_contract_id = contract.contract_id
            state.repeated_contract_count = 1
        signature = build_evidence_signature(result, contract)
        gain = has_information_gain(state.last_evidence_signature, signature, contract)
        state.attempted_verifiers.add(result.verifier_id)
        state.attempted_sources.update(source.value for source in result.sources)
        if result.strategy is not None:
            state.attempted_strategy_ids.add(result.strategy.value)

        if result.judgement in {
            EvidenceJudgement.VERIFIED,
            EvidenceJudgement.CONTRADICTED,
        }:
            state.reset(signature, step)
            return DebtUpdate(DebtAction.NORMAL, state, True)

        previous_target = (
            state.last_evidence_signature.verification_target
            if state.last_evidence_signature is not None
            else None
        )
        state.consecutive_unknown += 1
        if gain:
            state.no_new_evidence_count = 0
            state.debt_score = max(0, state.debt_score - 1)
            state.last_progress_step = step
        else:
            state.no_new_evidence_count += 1
            state.debt_score += 1
        state.repeated_target_count = (
            state.repeated_target_count + 1
            if result.verification_target == previous_target
            and result.verification_target is not None
            else 1
        )
        state.last_evidence_signature = signature
        return DebtUpdate(self._action_for(state), state, gain)

    def _action_for(self, state: VerificationDebtState) -> DebtAction:
        score = state.no_new_evidence_count
        if score >= self.config.hard_threshold:
            return DebtAction.UNVERIFIABLE
        if score >= self.config.hard_threshold - 1:
            return DebtAction.SWITCH_STRATEGY
        if score >= self.config.strategy_switch_threshold:
            return DebtAction.REGROUND_CONTRACT
        if score >= self.config.soft_threshold:
            return DebtAction.MARK_SUSPICIOUS
        return DebtAction.NORMAL
