"""Small orchestration layer for contract grounding and verification debt."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.schema import GuardResult, SuspicionReason, TaskNode
from ..environment.capabilities import EnvironmentCapabilities
from ..verification.contracts import AdaptiveEvidenceContract, EvidenceSource
from ..verification.grounder import (
    GroundingTrigger, VerificationGrounder, context_signature,
)
from ..verification.lifecycle import ContractStore
from ..verification.observation import ObservationBundle
from ..verification.registry import VerifierRegistry
from ..verification.result import (
    EvidenceGap, EvidenceJudgement, EvidenceResult, EvidenceStrategy, UnknownReason,
)
from ..verification.validator import validate_contract
from ..verification.unknowns import UnknownType
from .verification_debt import (
    DebtAction, DebtUpdate, VerificationDebtConfig, VerificationDebtTracker,
)


@dataclass(frozen=True)
class AdaptiveVerificationConfig:
    enabled: bool = True
    max_grounding_attempts: int = 2
    max_reground_per_node: int = 2
    ground_on_context_shift: bool = True
    debt_enabled: bool = True
    debt: VerificationDebtConfig = VerificationDebtConfig()


@dataclass(frozen=True)
class AdaptiveDecision:
    action: DebtAction
    context: str | None = None
    debt: DebtUpdate | None = None
    contract_revised: bool = False
    error: str | None = None


class AdaptiveVerificationController:
    def __init__(self, grounder: VerificationGrounder,
                 registry: VerifierRegistry,
                 config: AdaptiveVerificationConfig | None = None,
                 store: ContractStore | None = None):
        self.grounder = grounder
        self.registry = registry
        self.config = config or AdaptiveVerificationConfig()
        self.store = store or ContractStore()
        self.debt = VerificationDebtTracker(self.config.debt)
        self.grounding_attempts: dict[str, int] = {}
        self.reground_counts: dict[str, int] = {}
        self.metrics = {
            "contracts_generated": 0,
            "contract_revision_count": 0,
            "contract_validation_failure_count": 0,
            "semantic_weakening_rejected": 0,
            "contract_stale_count": 0,
            "nodes_unverifiable": 0,
            "verification_debt_trigger_count": 0,
            "evidence_source_switch_count": 0,
            "reground_budget_exhaustion_count": 0,
        }

    def on_plan_patch(self, replacements: dict[str, str]) -> None:
        """Retire removed contracts and preserve cross-replan source memory."""
        self.store.retire_nodes(replacements)
        for old_node_id, new_node_id in replacements.items():
            self.debt.remap_node(old_node_id, new_node_id)
            self.grounding_attempts.pop(old_node_id, None)
            self.grounding_attempts.setdefault(new_node_id, 0)
            previous_regrounds = self.reground_counts.pop(old_node_id, 0)
            self.reground_counts[new_node_id] = previous_regrounds

    def final_invariants_hold(self, task_state) -> bool:
        """Structural completion gate independent of the executor's finish claim.

        Environment-specific truth is established by each node's verifier. This gate
        makes sure the evidence still refers to the immutable semantic goal that was
        planned, preventing a revised contract from silently moving the goalpost.
        """
        for node in task_state.nodes.values():
            if not node.required:
                continue
            contract = self.store.active(node.node_id)
            if node.status.value != "verified" or not node.evidence:
                return False
            if contract is None or contract.semantic_goal_ref != node.semantic_goal.reference:
                return False
            if contract.success_condition != node.semantic_goal.invariant:
                return False
            if not any(item.contract_id == contract.contract_id for item in node.evidence):
                return False
        return True

    def preflight(self, task_state,
                  capabilities: EnvironmentCapabilities) -> tuple[str, ...]:
        return tuple(
            node.node_id for node in task_state.nodes.values()
            if node.required and not self.grounder.is_feasible(node, capabilities)
        )

    @staticmethod
    def context_shifted(contract: AdaptiveEvidenceContract, observation) -> bool:
        bundle = (observation if isinstance(observation, ObservationBundle)
                  else ObservationBundle.from_observation(observation))
        current = context_signature(bundle)
        identity_fields = ("active_app", "window", "page", "modal")
        return any(
            contract.context_signature.get(field) is not None
            and current.get(field) is not None
            and contract.context_signature[field] != current[field]
            for field in identity_fields
        )

    def ensure_contract(self, node: TaskNode, observation,
                        capabilities: EnvironmentCapabilities,
                        trigger: GroundingTrigger = GroundingTrigger.NODE_ACTIVATED,
                        trace_summary=None, failure_reason: str | None = None,
                        excluded_sources: frozenset[EvidenceSource] = frozenset()) \
            -> AdaptiveDecision:
        if not self.config.enabled:
            return AdaptiveDecision(DebtAction.NORMAL)
        bundle = (observation if isinstance(observation, ObservationBundle)
                  else ObservationBundle.from_observation(observation))
        previous = self.store.active(node.node_id)
        is_reground = previous is not None and trigger != GroundingTrigger.NODE_ACTIVATED
        if is_reground:
            count = self.reground_counts.get(node.node_id, 0)
            if count >= self.config.max_reground_per_node:
                self.metrics["reground_budget_exhaustion_count"] += 1
                return AdaptiveDecision(
                    DebtAction.UNVERIFIABLE,
                    error=f"reground budget exhausted for {node.node_id}")
            self.reground_counts[node.node_id] = count + 1
        if previous is None and isinstance(node.evidence_contract, AdaptiveEvidenceContract):
            existing = node.evidence_contract
            validation = validate_contract(
                node, None, existing, capabilities, self.registry)
            if validation.valid:
                self.store.attach(existing, trigger.value,
                                  bundle.step)
                node.active_contract_id = existing.contract_id
                return AdaptiveDecision(DebtAction.NORMAL)
        attempts = self.grounding_attempts.get(node.node_id, 0)
        if attempts >= self.config.max_grounding_attempts:
            self.metrics["nodes_unverifiable"] += 1
            return AdaptiveDecision(
                DebtAction.UNVERIFIABLE,
                error=f"grounding attempts exhausted for {node.node_id}")
        self.grounding_attempts[node.node_id] = attempts + 1
        result = self.grounder.ground(
            node, bundle, capabilities, previous, trigger, trace_summary,
            excluded_sources)
        if not result.groundable:
            self.metrics["contract_validation_failure_count"] += 1
            return AdaptiveDecision(DebtAction.UNVERIFIABLE, error=result.reason)
        validation = validate_contract(
            node, previous, result.contract, capabilities, self.registry)
        if not validation.valid:
            self.metrics["contract_validation_failure_count"] += 1
            self.metrics["semantic_weakening_rejected"] += int(
                not validation.no_weakening or not validation.semantic_preserved)
            self.store.reject(
                node.node_id, trigger.value, bundle.step,
                validation.rejection_reason or "invalid contract",
                result.contract.contract_id)
            return AdaptiveDecision(
                DebtAction.UNVERIFIABLE, error=validation.rejection_reason)
        self.store.attach(
            result.contract, trigger.value, bundle.step, failure_reason)
        node.evidence_contract = result.contract
        node.active_contract_id = result.contract.contract_id
        self.metrics["contracts_generated"] += 1
        if previous:
            self.metrics["contract_revision_count"] += 1
            self.metrics["evidence_source_switch_count"] += int(
                previous.sources != result.contract.sources)
        self.grounding_attempts[node.node_id] = 0
        return AdaptiveDecision(
            DebtAction.NORMAL, contract_revised=previous is not None)

    def observe_result(self, node: TaskNode, guard: GuardResult, step: int,
                       observation, capabilities: EnvironmentCapabilities,
                       trace_summary=None) -> AdaptiveDecision:
        contract = self.store.active(node.node_id)
        if contract is None:
            return AdaptiveDecision(
                DebtAction.UNVERIFIABLE, error="node has no active adaptive contract")
        if guard.judgement != "unknown":
            evidence = EvidenceResult(
                judgement=EvidenceJudgement(guard.judgement),
                verifier_id=contract.preferred_verifier or "guard",
                sources=contract.sources,
                progress_evidence=True,
                active_contract_id=contract.contract_id,
            )
            update = (self.debt.update(node.node_id, contract, evidence, step)
                      if self.config.debt_enabled else None)
            return AdaptiveDecision(DebtAction.NORMAL, debt=update)

        reason = UnknownReason(
            guard.unknown_reason or UnknownReason.NEED_MORE_EVIDENCE.value)
        unknown_type = getattr(guard, "unknown_type", None)
        if unknown_type == UnknownType.GUARD_CAPABILITY_INSUFFICIENT.value:
            reason = UnknownReason.VERIFIER_INCONCLUSIVE
        elif unknown_type in {
                UnknownType.HIDDEN_OR_PERSISTENT_STATE.value,
                UnknownType.ENVIRONMENT_STATE_MISSING.value}:
            reason = UnknownReason.SOURCE_UNAVAILABLE
        elif unknown_type == UnknownType.CONTRACT_UNVERIFIABLE.value \
                and reason == UnknownReason.NEED_MORE_EVIDENCE:
            reason = UnknownReason.CONTRACT_STALE
        strategy = _strategy_from_gap(guard.evidence_gap)
        evidence = EvidenceResult.unknown(
            contract.preferred_verifier or "guard",
            sources=contract.sources,
            target=guard.verification_target,
            reason=guard.reason,
            strategy=strategy,
            gap=_gap_from_dict(guard.evidence_gap),
            unknown_reason=reason,
            active_contract_id=contract.contract_id,
        )
        update = (self.debt.update(node.node_id, contract, evidence, step)
                  if self.config.debt_enabled else None)
        debt_action = update.action if update else DebtAction.NORMAL
        if debt_action != DebtAction.NORMAL:
            self.metrics["verification_debt_trigger_count"] += 1
        if reason == UnknownReason.CONTRACT_STALE:
            self.metrics["contract_stale_count"] += 1
        if reason in {UnknownReason.CONTRACT_STALE, UnknownReason.SOURCE_UNAVAILABLE} \
                or debt_action == DebtAction.REGROUND_CONTRACT:
            trigger = (GroundingTrigger.CONTRACT_STALE
                       if reason == UnknownReason.CONTRACT_STALE
                       else GroundingTrigger.REPEATED_UNKNOWN)
            grounded = self.ensure_contract(
                node, observation, capabilities, trigger, trace_summary, guard.reason,
                frozenset(EvidenceSource(value)
                          for value in (update.state.attempted_sources if update else ())))
            if grounded.action == DebtAction.NORMAL:
                return AdaptiveDecision(
                    DebtAction.NORMAL,
                    context="Verification contract was revised for the current UI.",
                    debt=update,
                    contract_revised=True)
            # Repeating the same unavailable/no-gain source is not a strategy
            # switch. Escalate to operational replanning while enough step budget
            # remains instead of cycling through equivalent screenshot contracts.
            return AdaptiveDecision(
                DebtAction.UNVERIFIABLE, debt=update,
                context=_strategy_context(guard), error=grounded.error)
        if reason == UnknownReason.NODE_UNVERIFIABLE \
                or debt_action == DebtAction.UNVERIFIABLE:
            self.store.mark_ungroundable(node.node_id)
            self.metrics["nodes_unverifiable"] += 1
            return AdaptiveDecision(DebtAction.UNVERIFIABLE, debt=update)
        if reason == UnknownReason.VERIFIER_INCONCLUSIVE \
                or debt_action == DebtAction.SWITCH_STRATEGY:
            if update:
                update.state.verifier_switch_count += 1
            return AdaptiveDecision(
                DebtAction.SWITCH_STRATEGY, debt=update,
                context=_strategy_context(guard))
        if debt_action == DebtAction.MARK_SUSPICIOUS:
            return AdaptiveDecision(
                DebtAction.MARK_SUSPICIOUS, debt=update,
                context=SuspicionReason.EXECUTOR_OVERCLAIM.value)
        return AdaptiveDecision(
            DebtAction.NORMAL, debt=update,
            context=guard.verification_target)


def _strategy_from_gap(value) -> EvidenceStrategy | None:
    if not value:
        return None
    strategy = value.get("recommended_strategy") or value.get("attempted_strategy")
    return EvidenceStrategy(strategy) if strategy else None


def _gap_from_dict(value) -> EvidenceGap | None:
    if not value:
        return None
    return EvidenceGap(
        missing_evidence=tuple(value.get("missing_evidence", ())),
        available_evidence=tuple(value.get("available_evidence", ())),
        unavailable_evidence=tuple(value.get("unavailable_evidence", ())),
        attempted_strategy=(EvidenceStrategy(value["attempted_strategy"])
                            if value.get("attempted_strategy") else None),
        recommended_strategy=(EvidenceStrategy(value["recommended_strategy"])
                              if value.get("recommended_strategy") else None),
        requires_new_source=bool(value.get("requires_new_source", False)),
        same_contract=bool(value.get("same_contract", True)),
    )


def _strategy_context(guard: GuardResult) -> str:
    gap = guard.evidence_gap or {}
    strategy = gap.get("recommended_strategy")
    missing = ", ".join(gap.get("missing_evidence", ())) or guard.verification_target
    return f"Acquire different evidence using {strategy or 'an alternate verifier'}: {missing}."
