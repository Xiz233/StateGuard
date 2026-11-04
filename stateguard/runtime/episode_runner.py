from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import nullcontext
import json

from ..core.action_capabilities import default_effect_observability
from ..core.action_similarity import actions_equivalent
from ..core.observability import CapabilityResolver
from ..core.dependency_graph import DependencyGraph
from ..core.schema import (Evidence, FaultType, GuardResult, NodeStatus,
                           RepairRequest, VerificationRequest)
from ..core.task_state import VerifiedTaskState
from ..guard.repair import build_repair_request, propagate_failure
from .checkpoint_policy import CheckpointDecision, CheckpointPolicy
from .checkpoint_policy import CompletionClaimTracker
from .events import InterventionEvent, RootPredictionEvent
from .observation_similarity import observations_near_equal
from .repair_loop import RepairBudget
from ..trace import TraceCollector, TraceStorage
from ..trace.analyzer import summarize_node_trace
from ..environment.capabilities import EnvironmentCapabilities
from ..verification.contracts import EvidenceSource
from ..verification.grounder import GroundingTrigger
from ..verification.result import UnknownReason
from .adaptive_verification import AdaptiveVerificationController
from .verification_debt import DebtAction
from ..planning.patch_validator import apply_plan_patch
from ..planning.runtime_replanner import LocalReplanRequest, RuntimeReplanner
from ..guard.backends.mllm_backend import GuardCallBudgetExceeded


@dataclass
class EpisodeResult:
    status: str
    success: bool
    total_steps: int
    task_state: object
    fault_events: list = field(default_factory=list)
    failure_exposure_events: list = field(default_factory=list)
    repair_events: list = field(default_factory=list)
    root_predictions: list = field(default_factory=list)
    intervention_events: list = field(default_factory=list)
    preserved_nodes: list = field(default_factory=list)
    reactivated_nodes: list = field(default_factory=list)
    executor_calls: int = 0
    guard_calls: int = 0
    executor_tokens: int = 0
    guard_tokens: int = 0
    executor_latency: float = 0.0
    guard_latency: float = 0.0
    grounder_calls: int = 0
    grounder_tokens: int = 0
    grounder_latency: float = 0.0
    replanner_calls: int = 0
    replanner_tokens: int = 0
    replanner_latency: float = 0.0
    environment_score: float = 0.0
    evaluator_details: dict | None = None
    evaluator_exception: str | None = None
    error: str | None = None
    fault_injected_step: int | None = None
    failure_exposed_step: int | None = None
    guard_first_detection_step: int | None = None
    guard_detection_delay: int | None = None
    early_detection: bool = False
    first_root_prediction: str | None = None
    eventual_root_prediction: str | None = None
    first_root_accuracy: float = 0.0
    eventual_root_accuracy: float = 0.0
    repair_cycle_count: int = 0
    repair_action_count: int = 0
    repair_budget_exhaustions: list = field(default_factory=list)
    suspicious_checkpoint_count: int = 0
    trace_entry_count: int = 0
    preservable_nodes: list = field(default_factory=list)
    actually_preserved_nodes: list = field(default_factory=list)
    reexecuted_preserved_nodes: list = field(default_factory=list)
    state_preservation_rate: float = 1.0
    strict_progress_preservation_rate: float = 1.0
    guard_intervention_count: int = 0
    certified_clean: bool = False
    false_intervention_episode: bool = False
    false_intervention_event_count: int = 0
    fault_reexecution_observed: bool = False
    # sparse verification / auto-dag metrics
    dag_source: str | None = None
    dag_node_count: int | None = None
    dag_edge_count: int | None = None
    dag_generation_valid: bool | None = None
    dag_generation_attempts: int | None = None
    dag_generation_calls: int = 0
    dag_generation_tokens: int = 0
    dag_generation_latency: float = 0.0
    frontier_violation_count: int = 0
    frontier_recovery_count: int = 0
    checkpoint_count: int = 0
    checkpoint_reasons: list = field(default_factory=list)
    checkpoint_kinds: list = field(default_factory=list)
    verification_calls: int = 0
    unknown_checkpoint_count: int = 0
    max_consecutive_unknown_observed: int = 0
    unknown_type_counts: dict = field(default_factory=dict)
    contradiction_count: int = 0
    premature_finish_count: int = 0
    plan_revision_count: int = 0
    local_replan_count: int = 0
    local_replan_success_count: int = 0
    contracts_generated: int = 0
    contract_revision_count: int = 0
    contract_validation_failure_count: int = 0
    semantic_weakening_rejected: int = 0
    contract_stale_count: int = 0
    nodes_unverifiable: int = 0
    verification_debt_trigger_count: int = 0
    evidence_source_switch_count: int = 0
    reground_budget_exhaustion_count: int = 0
    executor_overclaim_count: int = 0
    executor_finish_reconciliation_count: int = 0
    guard_parse_fail_open_count: int = 0
    guard_strategy_normalization_count: int = 0
    guard_progress_update_drop_count: int = 0
    replanner_fallback_count: int = 0
    actions_per_subgoal: dict = field(default_factory=dict)
    steps_between_checkpoints: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def steps(self): return self.total_steps

    def to_dict(self):
        value = asdict(self); value["task_state"] = self.task_state.serialize(); return value


class EpisodeRunner:
    LATEST_RETRY_PROMPT = (
        "The current task state indicates that recent progress may not be correct. "
        "Inspect the current screen and revise the most recent relevant operation.")

    def __init__(self, executor, guard=None, max_total_steps=50,
                 max_repair_cycles_per_fault=3, max_unknown_verification_cycles=3,
                 mode="stateguard", history=None, verification_policy="dense",
                 checkpoint_policy=None, max_repair_actions_per_cycle=20,
                 trace_collector=None, trace_max_entries=200,
                 trace_keep_recent_images=10,
                 unchanged_observation_threshold=3,
                 adaptive_controller: AdaptiveVerificationController | None = None,
                 runtime_replanner: RuntimeReplanner | None = None,
                 max_replans_per_node: int = 2,
                 max_replans_per_episode: int = 5,
                 max_consecutive_unknown: int = 8,
                 final_invariant_verifier=None,
                 suppress_repeated_completion_claims: bool = True):
        self.executor, self.guard, self.max_steps = executor, guard, max_total_steps
        self.mode, self.history = mode, history
        self.budget = RepairBudget(max_repair_cycles_per_fault,
                                   max_repair_actions_per_cycle)
        self.max_unknown = max_unknown_verification_cycles
        self.verification_policy = verification_policy
        self.checkpoint_policy = checkpoint_policy or CheckpointPolicy(verification_policy)
        self.trace_collector = trace_collector
        self.trace_max_entries = trace_max_entries
        self.trace_keep_recent_images = trace_keep_recent_images
        self.unchanged_observation_threshold = max(
            3, int(unchanged_observation_threshold))
        self.adaptive_controller = adaptive_controller
        self.runtime_replanner = runtime_replanner
        self.max_replans_per_node = max(1, int(max_replans_per_node))
        self.max_replans_per_episode = max(1, int(max_replans_per_episode))
        self.max_consecutive_unknown = max(1, int(max_consecutive_unknown))
        self.final_invariant_verifier = final_invariant_verifier
        self.completion_claims = (
            CompletionClaimTracker() if suppress_repeated_completion_claims else None)

    @staticmethod
    def _repair_phase(task_state, repair):
        if repair.fault_root not in task_state:
            return None
        if task_state.get(repair.fault_root).status != NodeStatus.VERIFIED:
            return "RESTORE_ROOT"
        stale = [nid for nid in repair.reverify_nodes
                 if nid in task_state and task_state.get(nid).status == NodeStatus.STALE]
        return "REPAIR_INVALID_DESCENDANTS" if stale else "VERIFY_DESCENDANTS"

    @staticmethod
    def _repair_complete(task_state, repair):
        return bool(repair.reverify_nodes) and all(
            node_id in task_state
            and task_state.get(node_id).status == NodeStatus.VERIFIED
            for node_id in repair.reverify_nodes)

    @staticmethod
    def _same_intended_action(first, second):
        return actions_equivalent(first, second)

    @staticmethod
    def _stagnation_result(task_state, node_id, action, step, confirmed):
        reason = (
            "Repeated nearby actions produced UNKNOWN while the visible state remained "
            "unchanged."
        )
        if not confirmed:
            return GuardResult(
                "unknown",
                state_updates=[{
                    "op": "suspicious", "node_id": node_id,
                    "reason": reason, "step_id": step,
                }],
                verification_target=(
                    "Use a different action type or UI region and obtain visible evidence "
                    "for this subgoal."),
                reason=f"Stagnation suspected: {reason}",
            )

        shadow = VerifiedTaskState.deserialize(task_state.serialize())
        graph = DependencyGraph.from_state(shadow)
        root_status = shadow.get(node_id).status
        stale = propagate_failure(shadow, graph, node_id)
        updates = []
        if root_status not in {NodeStatus.PENDING, NodeStatus.FAILED}:
            updates.append({"op": "fail", "node_id": node_id})
        if stale:
            updates.append({"op": "stale", "node_ids": stale})
        repair = build_repair_request(
            shadow, graph, node_id, FaultType.NO_EFFECT.value, 0.9)
        repair.goal += (
            f" The action {action!r}, including nearby coordinates, is blocked; "
            "choose a different action type or UI region."
        )
        return GuardResult(
            "contradicted", fault_root=node_id,
            fault_type=FaultType.NO_EFFECT.value, repair=repair,
            state_updates=updates,
            reason=f"Stagnation confirmed: {reason}",
        )

    @staticmethod
    def _action_stagnation_result(task_state, node_id, action, step):
        reason = (
            "The current action repeatedly produced UNKNOWN with no observable "
            "change. Block this action without treating it as a node-level failure."
        )
        updates = []
        if task_state.get(node_id).status == NodeStatus.EXECUTED:
            updates.append({
                "op": "suspicious", "node_id": node_id,
                "reason": reason, "step_id": step,
            })
        return GuardResult(
            "unknown", state_updates=updates,
            verification_target=(
                f"Do not repeat {action!r}; use a different action type or UI region "
                "while continuing the current subgoal."),
            reason=f"Action stagnation: {reason}",
        )

    @staticmethod
    def _effect_observability(proposal):
        action = proposal.action if isinstance(proposal.action, dict) else {}
        observability = getattr(proposal, "effect_observability", "auto")
        if observability == "auto":
            observability = default_effect_observability(action)
        return observability

    @classmethod
    def _action_supports_no_effect(cls, proposal):
        return cls._effect_observability(proposal) in {"visual", "structured"}

    @classmethod
    def _observation_effect_unchanged(cls, proposal, before, after):
        channel = cls._effect_observability(proposal)
        if channel == "visual":
            return observations_near_equal(before, after)
        if channel == "structured":
            return (
                before.structured_state is not None
                and after.structured_state is not None
                and before.structured_state == after.structured_state
            )
        return False

    @staticmethod
    def _mark_action_executed(task_state, node_id):
        """Record that an action ran without making a verification claim."""
        if not node_id or node_id not in task_state.nodes:
            return
        node = task_state.get(node_id)
        if node.status in (NodeStatus.PENDING, NodeStatus.FAILED, NodeStatus.STALE):
            task_state.mark_active(node_id)
            node = task_state.get(node_id)
        if node.status == NodeStatus.ACTIVE:
            task_state.mark_executed(node_id)

    @classmethod
    def _advance_baseline_state(cls, task_state, proposal, step=0):
        """Advance the control baseline from Executor claims, not Guard evidence.

        Both paired modes receive the same DAG/frontier prompt. In executor-only
        mode, a subgoal_done claim is the only available progress signal, so it is
        recorded explicitly as untrusted executor-claim evidence. StateGuard mode
        instead requires Guard evidence before a node becomes VERIFIED.
        """
        # Keep the node-id form for callers that only need execution tracking.
        if isinstance(proposal, str):
            cls._mark_action_executed(task_state, proposal)
            return
        node_id = proposal.subgoal_id
        cls._mark_action_executed(task_state, node_id)
        if not proposal.subgoal_done or node_id not in task_state.nodes:
            return
        node = task_state.get(node_id)
        if node.status == NodeStatus.EXECUTED:
            task_state.mark_verified(node_id, Evidence(
                step, "executor_claim",
                proposal.expected_effect or proposal.intent or "executor claimed completion",
                0.0,
            ))

    @staticmethod
    def _frontier(task_state):
        return set(DependencyGraph.from_state(task_state).executable_frontier(task_state))

    @staticmethod
    def _environment_capabilities(env, observation):
        if hasattr(env, "get_capabilities"):
            return env.get_capabilities(observation)
        sources = {EvidenceSource.SCREENSHOT}
        if getattr(observation, "ui_tree", None) is not None:
            sources.add(EvidenceSource.ACCESSIBILITY_TREE)
        if getattr(observation, "structured_state", None) is not None:
            sources.add(EvidenceSource.STRUCTURED_STATE)
        verifiers = {"visual_mllm"}
        if EvidenceSource.ACCESSIBILITY_TREE in sources:
            verifiers.add("accessibility_predicate")
        if EvidenceSource.STRUCTURED_STATE in sources:
            verifiers.add("structured_predicate")
        if EvidenceSource.EXTERNAL_TOOL in sources:
            verifiers.add("persistence")
        return EnvironmentCapabilities(
            available_sources=frozenset(sources),
            supported_verifiers=frozenset(verifiers),
        )

    @staticmethod
    def _strategy_id(proposal, resolved_observability) -> str:
        action = proposal.action if isinstance(proposal.action, dict) else {}
        return json.dumps({
            "action_type": action.get("type") or action.get("action_type"),
            "sources": [source.value for source in getattr(
                resolved_observability, "sources", ())],
            "verifiers": list(getattr(
                resolved_observability, "verifier_candidates", ())),
        }, sort_keys=True, default=str)

    def run(self, env, task_state, task_spec=None, task_id="task", injector=None, logger=None,
            dag_provider=None):
        task_spec = task_spec or {}
        injections, exposures, repairs, roots, interventions = [], [], [], [], []
        invalidated, repair_targets, verified_before_fault = set(), set(), set()
        reactivated, unknown_cycles = set(), {}
        sparse_stagnation_cycles = {}
        nonvisual_unknown_cycles = {}
        blocked_strategy_counts = {}
        injected_original_action = injected_root = None
        fault_reexecution_observed = False
        active_repair = next_context = None
        repair_cycles = repair_actions = 0
        repair_budget_exhaustions = []
        suspicious_checkpoint_count = 0
        sparse = (self.verification_policy in {"sparse", "hybrid"}
                  and self.mode == "stateguard")
        checkpoint_count = 0
        checkpoint_reasons: list[str] = []
        checkpoint_kinds: list[str] = []
        verification_calls = 0
        unknown_checkpoint_count = 0
        consecutive_unknown = 0
        max_observed_consecutive_unknown = 0
        unknown_type_counts: dict[str, int] = {}
        contradiction_count = 0
        premature_finish_count = 0
        plan_revision_count = 0
        local_replan_count = local_replan_success_count = 0
        replans_per_node: dict[str, int] = {}
        frontier_violations = 0
        frontier_recovery_count = 0
        actions_per_subgoal: dict = {}
        steps_between_checkpoints: list[int] = []
        last_checkpoint_step = 0
        obs, status, error = env.reset(task_spec), "max_steps", None
        capabilities = self._environment_capabilities(env, obs)
        trace = self.trace_collector
        if trace is None:
            trace_path = getattr(logger, "dir", None)
            trace = TraceCollector(
                TraceStorage(trace_path / "execution_trace.jsonl" if trace_path else None,
                             self.trace_max_entries),
                self.trace_keep_recent_images)
        if self.guard is not None and hasattr(self.guard, "trace_collector"):
            self.guard.trace_collector = trace
        if dag_provider is not None:
            try:
                task_state = dag_provider(obs)
            except Exception as exc:
                status, error = "auto_dag_failed", str(exc)
        dag_failed = status == "auto_dag_failed"

        def trace_summary(node_id):
            if self.adaptive_controller is None:
                return None
            contract = self.adaptive_controller.store.active(node_id)
            semantic_key = (getattr(contract, "semantic_goal_ref", "")
                            or getattr(contract, "contract_id", ""))
            debt = (self.adaptive_controller.debt.state_for(node_id, semantic_key).debt_score
                    if semantic_key else 0)
            return summarize_node_trace(
                trace.storage.entries, node_id,
                self.adaptive_controller.store.events, debt).to_dict()

        def attempt_local_replan(node_id, current_step, observation):
            nonlocal task_state, plan_revision_count, local_replan_count
            nonlocal local_replan_success_count, status, error
            nonlocal active_repair, next_context, injected_root
            local_replan_count += 1
            plan_revision_count += 1
            replan_state = task_state.serialize()
            replan_event = (logger.start_event(
                "local_replan", current_step, replan_state,
                node_id=node_id,
                observation_artifact_id=logger.record_observation(
                    observation, "replan_observation",
                    f"step-{current_step}-replan"))
                if logger else None)
            count = replans_per_node.get(node_id, 0)
            if (self.runtime_replanner is None
                    or count >= self.max_replans_per_node
                    or local_replan_count > self.max_replans_per_episode):
                status = "plan_revision_failed"
                error = f"local replan unavailable or exhausted for {node_id}"
                if logger:
                    logger.finish_event(
                        replan_event, "local_replan", current_step,
                        replan_state, task_state.serialize(), "failed",
                        exception=error)
                return False
            replans_per_node[node_id] = count + 1
            graph = DependencyGraph.from_state(task_state)
            node = task_state.get(node_id)
            contract = (self.adaptive_controller.store.active(node_id)
                        if self.adaptive_controller else None)
            debt_summary = trace_summary(node_id) or {}
            bundle = (env.collect_observation_bundle(observation)
                      if hasattr(env, "collect_observation_bundle") else
                      {"step": getattr(observation, "step", current_step),
                       "metadata": getattr(observation, "metadata", {})})
            raw_summary = (
                bundle.__dict__.copy() if hasattr(bundle, "__dict__") else dict(bundle))
            observation_summary = {
                key: value for key, value in raw_summary.items()
                if key not in {"screenshot", "accessibility_tree"}
            }
            observation_summary["has_screenshot"] = bool(raw_summary.get("screenshot"))
            observation_summary["has_accessibility_tree"] = bool(
                raw_summary.get("accessibility_tree"))
            request = LocalReplanRequest(
                task_goal=str(task_spec.get("instruction", "")),
                problem_node=node.to_dict(),
                ancestor_boundary=tuple(task_state.get(nid).to_dict()
                                        for nid in graph.ancestors(node_id)),
                descendant_boundary=tuple(task_state.get(nid).to_dict()
                                          for nid in graph.children(node_id)),
                current_observation_summary=observation_summary,
                environment_capabilities=capabilities.to_dict(),
                verification_debt_summary=debt_summary,
                attempted_strategies=tuple(
                    debt_summary.get("unique_verifiers", ())),
                trace_summary=debt_summary,
                protected_verified_nodes=tuple(task_state.verified_nodes()),
            )
            try:
                binding = logger.bind_event(replan_event) if logger else nullcontext()
                with binding:
                    patch = self.runtime_replanner.replan(request)
                patched = apply_plan_patch(
                    task_state.nodes, patch, capabilities,
                    self.adaptive_controller.registry if self.adaptive_controller else None,
                    protected_node_ids=set(task_state.verified_nodes()))
                patched_state = VerifiedTaskState.deserialize({"nodes": patched})
                replacements = {
                    replaced: patch.replacement_anchor
                    for replaced in patch.replace_nodes
                }
                remapped_repair = (
                    active_repair.remap_nodes(
                        replacements, set(patched_state.nodes))
                    if active_repair is not None else None)
                task_state = patched_state
                if active_repair is not None:
                    old_root = active_repair.fault_root
                    active_repair = remapped_repair
                    self.budget.remap_root(old_root, active_repair.fault_root)
                for runtime_ids in (
                        invalidated, repair_targets, verified_before_fault, reactivated):
                    mapped_ids = {
                        replacements.get(value, value) for value in runtime_ids
                        if replacements.get(value, value) in patched_state
                    }
                    runtime_ids.clear()
                    runtime_ids.update(mapped_ids)
                if active_repair is not None:
                    repair_targets.update(active_repair.reverify_nodes)
                    reactivated.update(active_repair.reverify_nodes)
                if injected_root is not None:
                    injected_root = replacements.get(injected_root, injected_root)
                if isinstance(next_context, VerificationRequest):
                    mapped = replacements.get(
                        next_context.subgoal_id, next_context.subgoal_id)
                    next_context = VerificationRequest(
                        next_context.target, mapped, next_context.cycles)
                for removed in patch.replace_nodes:
                    unknown_cycles.pop(removed, None)
                    sparse_stagnation_cycles.pop(removed, None)
                    nonvisual_unknown_cycles.pop(removed, None)
                    blocked_strategy_counts.pop(removed, None)
                inherited_replans = max(
                    (replans_per_node.pop(removed, 0)
                     for removed in patch.replace_nodes), default=0)
                replans_per_node[patch.replacement_anchor] = max(
                    replans_per_node.get(patch.replacement_anchor, 0),
                    inherited_replans)
                self.checkpoint_policy.discard_nodes(patch.replace_nodes)
                if self.completion_claims is not None:
                    self.completion_claims.discard_nodes(patch.replace_nodes)
                if self.adaptive_controller is not None:
                    self.adaptive_controller.on_plan_patch(replacements)
            except Exception as exc:
                status = "plan_revision_failed"
                error = f"local replan failed for {node_id}: {exc}"
                if logger:
                    logger.finish_event(
                        replan_event, "local_replan", current_step,
                        replan_state, task_state.serialize(), "failed",
                        request=request.__dict__, exception=str(exc))
                return False
            local_replan_success_count += 1
            status, error = "max_steps", None
            if logger and hasattr(logger, "append"):
                logger.append("plan_patch_events.jsonl", {
                    "step": current_step, "node_id": node_id,
                    "patch": patch.to_dict(), "preserved": task_state.verified_nodes(),
                    "runtime_replacements": replacements,
                    "active_repair": (active_repair.to_dict()
                                      if active_repair is not None else None)})
                logger.finish_event(
                    replan_event, "local_replan", current_step,
                    replan_state, task_state.serialize(), "completed",
                    request=request.__dict__, patch=patch.to_dict(),
                    runtime_replacements=replacements)
                logger.record_intervention(
                    current_step, "replan", decision=request.__dict__,
                    execution=patch.to_dict(), immediate_result={"applied": True},
                    parent_event_id=replan_event)
            return True

        def handle_adaptive_result(node_id, guard_result, current_step, observation):
            if self.adaptive_controller is None or node_id not in task_state:
                return None
            decision = self.adaptive_controller.observe_result(
                task_state.get(node_id), guard_result, current_step,
                observation, capabilities, trace_summary(node_id))
            node = task_state.get(node_id)
            if decision.action == DebtAction.MARK_SUSPICIOUS \
                    and node.status == NodeStatus.EXECUTED:
                task_state.mark_suspicious(
                    node_id, decision.context or "executor_overclaim", current_step)
            elif decision.action == DebtAction.UNVERIFIABLE \
                    and node.status in {NodeStatus.EXECUTED, NodeStatus.SUSPICIOUS}:
                task_state.mark_unverifiable(
                    node_id, decision.error or "verification strategies exhausted")
            return decision

        def apply_adaptive_result(node_id, guard_result, current_step, observation):
            nonlocal next_context, plan_revision_count, revision_node
            decision = handle_adaptive_result(
                node_id, guard_result, current_step, observation)
            if decision is None:
                return None
            next_context = decision.context or next_context
            if decision.action == DebtAction.UNVERIFIABLE:
                revision_node = node_id
            elif decision.action == DebtAction.SWITCH_STRATEGY:
                plan_revision_count += 1
            if guard_result.judgement == "verified" and self.completion_claims:
                self.completion_claims.reset(node_id)
            return decision

        if self.adaptive_controller is not None and not dag_failed:
            for node_id in self.adaptive_controller.preflight(task_state, capabilities):
                if not attempt_local_replan(node_id, 0, obs):
                    break

        for step in range(1, self.max_steps + 1):
            if dag_failed or status == "plan_revision_failed":
                break
            frontier = self._frontier(task_state)
            if not frontier:
                if task_state.can_finish():
                    if (self.adaptive_controller is None
                            or self.adaptive_controller.final_invariants_hold(task_state)):
                        status = "completed"
                        if logger:
                            finish_state = task_state.serialize()
                            finish_event = logger.start_event(
                                "finish_decision", step, finish_state,
                                decision_source="runtime_frontier",
                                observation_artifact_id=logger.record_observation(
                                    obs, "finish_observation",
                                    f"step-{step}-runtime-finish"))
                            logger.finish_event(
                                finish_event, "finish_decision", step,
                                finish_state, task_state.serialize(), "completed",
                                approved=True, guard_invoked=False,
                                reason="all required states verified and invariants hold")
                        break
                    stale = next((
                        node_id for node_id in task_state.verified_nodes()
                        if not any(
                            item.contract_id == getattr(
                                self.adaptive_controller.store.active(node_id),
                                "contract_id", None)
                            for item in task_state.get(node_id).evidence
                        )
                    ), None)
                    if stale is not None:
                        task_state.mark_suspicious(
                            stale, "active verification contract lacks matching evidence", step)
                        frontier_recovery_count += 1
                        continue
                # An empty frontier with incomplete required nodes is a runtime
                # graph/state inconsistency. Diagnose and replan before asking the
                # Executor to guess an impossible subgoal.
                incomplete = task_state.incomplete_required_nodes()
                recovery_node = next((node_id for node_id in incomplete
                                      if node_id in task_state), None)
                if recovery_node and self.runtime_replanner is not None:
                    frontier_recovery_count += 1
                    if attempt_local_replan(recovery_node, step, obs):
                        continue
                status = "frontier_recovery_failed"
                error = ("empty executable frontier with incomplete required nodes: "
                         f"{sorted(incomplete)}")
                break
            if self.adaptive_controller is not None:
                replanned = False
                for frontier_node in sorted(self._frontier(task_state)):
                    active = self.adaptive_controller.store.active(frontier_node)
                    trigger = GroundingTrigger.NODE_ACTIVATED
                    if active is not None and not capabilities.has_sources(active.sources):
                        trigger = GroundingTrigger.EVIDENCE_SOURCE_FAILURE
                    elif active is not None and self.adaptive_controller.context_shifted(
                            active, obs) and self.adaptive_controller.config.ground_on_context_shift:
                        trigger = GroundingTrigger.CONTEXT_SHIFT
                    elif active is not None:
                        continue
                    try:
                        grounding = self.adaptive_controller.ensure_contract(
                            task_state.get(frontier_node), obs, capabilities,
                            trigger,
                            trace_summary(frontier_node))
                    except Exception as exc:
                        status, error = "model_failed", str(exc)
                        break
                    if grounding.action == DebtAction.UNVERIFIABLE:
                        node = task_state.get(frontier_node)
                        if node.status in {NodeStatus.EXECUTED, NodeStatus.SUSPICIOUS}:
                            task_state.mark_unverifiable(frontier_node, grounding.error or "")
                        replanned = attempt_local_replan(frontier_node, step, obs)
                        if not replanned:
                            break
                if status in {"model_failed", "plan_revision_failed"}:
                    break
                if replanned:
                    continue
            context = active_repair or next_context
            repair_phase = self._repair_phase(task_state, active_repair) if active_repair else None
            if active_repair is not None and repair_phase is None:
                status = "plan_revision_failed"
                error = (
                    f"active repair root {active_repair.fault_root!r} is absent "
                    "from the current task graph")
                break
            phase = ("repair" if active_repair else
                     "verification" if isinstance(next_context, VerificationRequest) else "normal")
            phase_cycle_id = getattr(active_repair, "repair_cycle_id", None)
            next_context = None
            decision_state = task_state.serialize()
            decision_event = (logger.start_event(
                "executor_decision", step, decision_state,
                observation_before_artifact_id=logger.record_observation(
                    obs, "executor_observation", f"step-{step}-executor"),
                execution_phase=repair_phase or phase,
                context=context)
                if logger else None)
            try:
                binding = logger.bind_event(decision_event) if logger else nullcontext()
                with binding:
                    proposal = self.executor.act(obs, task_state, context)
            except ValueError as exc:
                status, error = "executor_parse_failed", str(exc)
                if logger:
                    logger.finish_event(
                        decision_event, "executor_decision", step,
                        decision_state, task_state.serialize(), "failed",
                        failure_type="parse_failure", exception=str(exc))
                break
            except Exception as exc:
                status, error = "model_failed", str(exc)
                if logger:
                    logger.finish_event(
                        decision_event, "executor_decision", step,
                        decision_state, task_state.serialize(), "failed",
                        failure_type="model_failure", exception=str(exc))
                break
            if proposal is None:
                status = "stalled"
                if logger:
                    logger.finish_event(
                        decision_event, "executor_decision", step,
                        decision_state, task_state.serialize(), "failed",
                        failure_type="empty_proposal")
                break
            if logger:
                logger.finish_event(
                    decision_event, "executor_decision", step,
                    decision_state, task_state.serialize(), "completed",
                    executor_proposal=proposal.to_dict())
            if (injected_original_action is not None
                    and proposal.subgoal_id == injected_root
                    and self._same_intended_action(proposal.action, injected_original_action)):
                fault_reexecution_observed = True
            step_interventions = []
            adaptive_decision = None
            revision_node = None
            if proposal.is_finish:
                finish_state = task_state.serialize()
                finish_event = (logger.start_event(
                    "finish_decision", step, finish_state,
                    executor_proposal=proposal.to_dict(),
                    observation_artifact_id=logger.record_observation(
                        obs, "finish_observation", f"step-{step}-finish"))
                    if logger else None)
                if self.mode != "stateguard":
                    status = "completed"
                    if logger:
                        logger.finish_event(
                            finish_event, "finish_decision", step, finish_state,
                            task_state.serialize(), "completed",
                            approved=True, guard_invoked=False)
                    break
                verification_calls += 1
                if sparse:
                    checkpoint_count += 1
                    checkpoint_reasons.append("finish")
                    checkpoint_kinds.append("finish")
                    steps_between_checkpoints.append(step - last_checkpoint_step)
                    last_checkpoint_step = step
                try:
                    binding = logger.bind_event(finish_event) if logger else nullcontext()
                    with binding:
                        result = self.guard.verify_finish(task_state, obs)
                    final_verifier = self.final_invariant_verifier
                    if final_verifier is None and self.adaptive_controller is not None:
                        final_verifier = lambda state, _obs, _spec: (
                            self.adaptive_controller.final_invariants_hold(state))
                    if result.approved and final_verifier is not None:
                        final = final_verifier(task_state, obs, task_spec)
                        approved = (final.approved if isinstance(final, GuardResult)
                                    else bool(final))
                        if not approved:
                            result = (final if isinstance(final, GuardResult) else GuardResult(
                                "unknown", verification_target="verify final task invariant",
                                reason="final invariant verifier rejected completion"))
                except GuardCallBudgetExceeded as exc:
                    status, error = "guard_budget_exhausted", str(exc)
                    if logger:
                        logger.finish_event(
                            finish_event, "finish_decision", step, finish_state,
                            task_state.serialize(), "failed",
                            failure_type="guard_call_budget", exception=str(exc))
                    break
                except ValueError as exc:
                    status, error = "guard_parse_failed", str(exc)
                    if logger:
                        logger.finish_event(
                            finish_event, "finish_decision", step, finish_state,
                            task_state.serialize(), "failed",
                            failure_type="guard_parse_failure", exception=str(exc))
                    break
                except Exception as exc:
                    status, error = "model_failed", str(exc)
                    if logger:
                        logger.finish_event(
                            finish_event, "finish_decision", step, finish_state,
                            task_state.serialize(), "failed",
                            failure_type="model_failure", exception=str(exc))
                    break
                if logger:
                    if result.judgement == "unknown":
                        logger.record_unknown(
                            finish_event, step, proposal.subgoal_id,
                            result.to_dict(), [finish_event])
                    else:
                        logger.resolve_unknowns(
                            proposal.subgoal_id,
                            "VALID" if result.judgement == "verified" else "FAILED",
                            step, [finish_event], "later_state")
                if result.approved:
                    consecutive_unknown = 0
                    status = "completed"
                    if logger:
                        logger.finish_event(
                            finish_event, "finish_decision", step, finish_state,
                            task_state.serialize(), "completed", approved=True,
                            guard_result=result.to_dict())
                    break
                if result.judgement == "unknown":
                    unknown_type = result.to_dict().get("unknown_type")
                    unknown_type_counts[unknown_type] = (
                        unknown_type_counts.get(unknown_type, 0) + 1)
                    consecutive_unknown += 1
                    max_observed_consecutive_unknown = max(
                        max_observed_consecutive_unknown, consecutive_unknown)
                else:
                    consecutive_unknown = 0
                if result.state_updates:
                    task_state.apply(result.state_updates)
                    for update in result.state_updates:
                        if update["op"] == "stale":
                            invalidated.update(update["node_ids"])
                        elif update["op"] == "fail":
                            invalidated.add(update["node_id"])
                premature_finish_count += 1
                event = InterventionEvent(step, "finish_rejection")
                interventions.append(event.to_dict()); step_interventions.append(event)
                if result.repair:
                    if result.repair.error_type == "premature_finish":
                        # A premature finish is NOT a causal repair: the guard's
                        # rule-based verify_finish just rejects an incomplete
                        # task. Do NOT consume the per-fault causal repair budget
                        # and do NOT enter the repair loop; give rule-based
                        # feedback so the executor returns to the frontier.
                        unverified = sorted(task_state.incomplete_required_nodes())
                        next_context = (
                            "Task cannot finish yet. Unverified required states: "
                            f"{', '.join(unverified)}. Continue working on one executable "
                            "frontier node.")
                    else:
                        contradiction_count += 1
                        repair_cycles += 1; result.repair.repair_cycle_id = repair_cycles
                        active_repair = result.repair; repairs.append(result.repair.to_dict())
                        if not self.budget.record(result.repair.fault_root):
                            status = "repair_failed"
                            repair_budget_exhaustions.append({
                                "fault_root": result.repair.fault_root,
                                "repair_cycle_id": repair_cycles,
                                "budget": "cycles_per_fault",
                                "limit": self.budget.limit,
                            })
                            break
                if logger:
                    logger.finish_event(
                        finish_event, "finish_decision", step, finish_state,
                        task_state.serialize(), "completed", approved=False,
                        guard_result=result.to_dict(),
                        intervention="finish_rejection")
                    logger.record_intervention(
                        step, "finish_rejection", decision=result.to_dict(),
                        execution={"continued": True},
                        immediate_result={"approved": False},
                        parent_event_id=finish_event)
                if consecutive_unknown >= self.max_consecutive_unknown:
                    status = "unknown_budget_exhausted"
                    error = ("consecutive UNKNOWN budget exhausted at "
                             f"{self.max_consecutive_unknown}")
                    break
                continue

            active_contract = (
                self.adaptive_controller.store.active(proposal.subgoal_id)
                if self.adaptive_controller and proposal.subgoal_id in task_state else None)
            resolved_observability = (
                CapabilityResolver.resolve(
                    proposal.action if isinstance(proposal.action, dict) else {},
                    active_contract, capabilities, self.adaptive_controller.registry,
                    declared_hint=getattr(proposal, "effect_observability", "auto"))
                if active_contract is not None else None)
            before_state, original = task_state.serialize(), proposal.action
            if active_repair and repair_phase == "RESTORE_ROOT" and not self.budget.record_action(
                    active_repair.fault_root, active_repair.repair_cycle_id):
                status = "repair_failed"
                repair_budget_exhaustions.append({
                    "fault_root": active_repair.fault_root,
                    "repair_cycle_id": active_repair.repair_cycle_id,
                    "budget": "actions_per_cycle",
                    "limit": self.budget.action_limit,
                })
                break
            executed, injection = (injector.inject(task_id, step, proposal, task_state)
                                   if injector else (original, None))
            trace.record_step(step, task_state, proposal=proposal,
                              executed_action=executed,
                              observation_before=obs,
                              execution_phase=repair_phase or phase,
                              contract=active_contract,
                              resolved_observability=resolved_observability,
                              capabilities=capabilities)
            if injection:
                verified_before_fault = {nid for nid, node in task_state.nodes.items()
                                         if node.status == NodeStatus.VERIFIED}
                injections.append(injection.to_dict())
                injected_original_action = original
                injected_root = injection.fault_root
                if hasattr(env, "note_fault_injection"):
                    env.note_fault_injection(injection, injector.spec)
            if phase == "repair":
                repair_actions += 1; repair_targets.add(proposal.subgoal_id)
            transition_event = (logger.start_event(
                "environment_transition", step, before_state,
                executor_proposal=proposal.to_dict(),
                proposed_action=original, executed_action=executed,
                observation_before_artifact_id=logger.record_observation(
                    obs, "pre_action_screenshot", f"step-{step}-transition"),
                execution_phase=repair_phase or phase)
                if logger else None)
            try:
                binding = logger.bind_event(transition_event) if logger else nullcontext()
                with binding:
                    after = env.step(executed)
            except Exception as exc:
                status, error = "environment_failed", str(exc)
                if logger:
                    logger.finish_event(
                        transition_event, "environment_transition", step,
                        before_state, task_state.serialize(), "failed",
                        execution_receipt=getattr(env, "last_execution_receipt", None),
                        failure_type="environment_exception", exception=str(exc))
                break
            capabilities = self._environment_capabilities(env, after)
            exposure = injector.poll_exposure(step, proposal) if injector else None
            if exposure:
                exposures.append(exposure.to_dict())
                if hasattr(env, "expose_failure"):
                    after = env.expose_failure(exposure)

            if self.mode in {"executor_only", "latest_retry"}:
                self._advance_baseline_state(task_state, proposal, step)
            elif sparse:
                self._mark_action_executed(task_state, proposal.subgoal_id)
            if not proposal.is_finish:
                actions_per_subgoal[proposal.subgoal_id] = (
                    actions_per_subgoal.get(proposal.subgoal_id, 0) + 1)

            result = None
            if sparse:
                # exposure never triggers a checkpoint (phase-8).
                if proposal.subgoal_id not in self._frontier(task_state):
                    frontier_violations += 1
                graph = DependencyGraph.from_state(task_state)
                candidates = (graph.ancestors(proposal.subgoal_id)
                              + [proposal.subgoal_id])
                decision = self.checkpoint_policy.evaluate(
                    proposal, task_state, graph, current_obs=obs,
                    previous_obs=None, history=self.history,
                    in_repair=bool(active_repair), repair_targets=repair_targets)
                if (decision.should_verify and proposal.subgoal_done
                        and self.completion_claims is not None
                        and active_contract is not None):
                    semantic_key = (active_contract.semantic_goal_ref
                                    or active_contract.contract_id)
                    debt_state = self.adaptive_controller.debt.state_for(
                        proposal.subgoal_id, semantic_key)
                    signature = (debt_state.last_evidence_signature.digest
                                 if debt_state.last_evidence_signature else None)
                    if not self.completion_claims.should_verify(
                            proposal.subgoal_id, active_contract.contract_id,
                            signature, self._strategy_id(proposal, resolved_observability)):
                        decision = CheckpointDecision(
                            False, "executor_overclaim", proposal.subgoal_id, "consistency")
                        result = GuardResult(
                            "unknown",
                            verification_target=(
                                "Acquire new evidence or use a different verification strategy "
                                "before claiming this subgoal is complete."),
                            reason="Repeated completion claim without information gain.",
                            unknown_reason=UnknownReason.NEED_MORE_EVIDENCE.value,
                            evidence_gap={
                                "missing_evidence": ["new evidence for completion"],
                                "available_evidence": [],
                                "unavailable_evidence": [],
                                "same_contract": True,
                            },
                            active_contract_id=active_contract.contract_id,
                        )
                        adaptive_decision = apply_adaptive_result(
                            proposal.subgoal_id, result, step, after)
                if decision.should_verify:
                    checkpoint_count += 1
                    checkpoint_reasons.append(decision.reason)
                    checkpoint_kinds.append(decision.checkpoint_kind)
                    steps_between_checkpoints.append(step - last_checkpoint_step)
                    last_checkpoint_step = step
                    verification_calls += 1
                    try:
                        binding = (logger.bind_event(transition_event)
                                   if logger else nullcontext())
                        with binding:
                            result = self.guard.verify_transition(
                                task_state, obs, proposal, after,
                                checkpoint_kind=decision.checkpoint_kind,
                                candidate_nodes=candidates)
                        raw_unknown = result.judgement == "unknown"
                        blocked_action = False
                        if raw_unknown:
                            unknown_checkpoint_count += 1
                            supports_no_effect = (
                                resolved_observability.directly_observable
                                if resolved_observability is not None
                                else self._action_supports_no_effect(proposal))
                            if not supports_no_effect:
                                count = nonvisual_unknown_cycles.get(
                                    proposal.subgoal_id, 0) + 1
                                nonvisual_unknown_cycles[proposal.subgoal_id] = count
                                if count == self.unchanged_observation_threshold:
                                    plan_revision_count += 1
                                    next_context = (
                                        "The current subgoal has produced repeated UNKNOWN "
                                        "judgements without an externally observable action effect. "
                                        "Revise the strategy so the next action creates direct visual, "
                                        "structured, or persistence evidence. Do not repeat passive "
                                        "inspection or private reasoning actions."
                                    )
                                elif count >= self.unchanged_observation_threshold * 2:
                                    if self.adaptive_controller is not None:
                                        revision_node = proposal.subgoal_id
                                    else:
                                        status = "plan_revision_required"
                                    error = (
                                        f"subgoal {proposal.subgoal_id} has no externally "
                                        "verifiable execution strategy after repeated UNKNOWN"
                                    )
                            previous_action, previous_count = sparse_stagnation_cycles.get(
                                proposal.subgoal_id, (None, 0))
                            repeated = actions_equivalent(
                                proposal.action, previous_action)
                            unchanged = self._observation_effect_unchanged(
                                proposal, obs, after)
                            count = (previous_count + 1
                                     if supports_no_effect and repeated and unchanged else 1)
                            sparse_stagnation_cycles[proposal.subgoal_id] = (
                                proposal.action, count)
                            if not supports_no_effect:
                                sparse_stagnation_cycles.pop(proposal.subgoal_id, None)
                            elif count >= self.unchanged_observation_threshold:
                                direct_completion = (
                                    proposal.subgoal_done
                                    and decision.checkpoint_kind in {"completion", "repair"}
                                )
                                if active_repair or not direct_completion:
                                    result = self._action_stagnation_result(
                                        task_state, proposal.subgoal_id,
                                        proposal.action, step)
                                    blocks = blocked_strategy_counts.get(
                                        proposal.subgoal_id, 0) + 1
                                    blocked_strategy_counts[proposal.subgoal_id] = blocks
                                    if blocks >= self.unchanged_observation_threshold:
                                        plan_revision_count += 1
                                        if self.adaptive_controller is not None:
                                            revision_node = proposal.subgoal_id
                                        else:
                                            status = "plan_revision_required"
                                        error = (
                                            f"subgoal {proposal.subgoal_id} exhausted "
                                            "multiple observable action strategies"
                                        )
                                else:
                                    result = self._stagnation_result(
                                        task_state, proposal.subgoal_id,
                                        proposal.action, step, confirmed=True)
                                sparse_stagnation_cycles.pop(proposal.subgoal_id, None)
                                blocked_action = True
                            elif count == self.unchanged_observation_threshold - 1:
                                result = self._stagnation_result(
                                    task_state, proposal.subgoal_id,
                                    proposal.action, step, confirmed=False)
                        else:
                            sparse_stagnation_cycles.pop(proposal.subgoal_id, None)
                            nonvisual_unknown_cycles.pop(proposal.subgoal_id, None)
                            blocked_strategy_counts.pop(proposal.subgoal_id, None)
                        task_state.apply(result.state_updates)
                        adaptive_decision = apply_adaptive_result(
                            proposal.subgoal_id, result, step, after)
                    except GuardCallBudgetExceeded as exc:
                        status, error = "guard_budget_exhausted", str(exc)
                        if logger:
                            logger.finish_event(
                                transition_event, "environment_transition", step,
                                before_state, task_state.serialize(), "failed",
                                execution_receipt=getattr(
                                    env, "last_execution_receipt", None),
                                failure_type="guard_call_budget", exception=str(exc))
                        break
                    except ValueError as exc:
                        status, error = "guard_parse_failed", str(exc)
                        if logger:
                            logger.finish_event(
                                transition_event, "environment_transition", step,
                                before_state, task_state.serialize(), "failed",
                                execution_receipt=getattr(
                                    env, "last_execution_receipt", None),
                                failure_type="guard_parse_failure", exception=str(exc))
                        break
                    except Exception as exc:
                        status, error = "model_failed", str(exc)
                        if logger:
                            logger.finish_event(
                                transition_event, "environment_transition", step,
                                before_state, task_state.serialize(), "failed",
                                execution_receipt=getattr(
                                    env, "last_execution_receipt", None),
                                failure_type="model_failure", exception=str(exc))
                        break
                    for update in result.state_updates:
                        if update["op"] == "stale": invalidated.update(update["node_ids"])
                        elif update["op"] == "fail": invalidated.add(update["node_id"])
                    if result.fault_root:
                        roots.append(RootPredictionEvent(step, result.fault_root).to_dict())
                    if result.repair:
                        contradiction_count += 1
                        repair_cycles += 1; result.repair.repair_cycle_id = repair_cycles
                        active_repair = result.repair; repairs.append(result.repair.to_dict())
                        reactivated.update(result.repair.reverify_nodes)
                        event = InterventionEvent(step, "repair_request", repair_cycles)
                        interventions.append(event.to_dict()); step_interventions.append(event)
                        if not self.budget.record(result.repair.fault_root):
                            status = "repair_failed"
                            repair_budget_exhaustions.append({
                                "fault_root": result.repair.fault_root,
                                "repair_cycle_id": repair_cycles,
                                "budget": "cycles_per_fault",
                                "limit": self.budget.limit,
                            })
                    elif result.judgement == "unknown":
                        # UNKNOWN is not failure, not repair, not immediate re-query:
                        # the node stays unresolved and the executor continues.
                        if any(u.get("op") == "suspicious" for u in result.state_updates):
                            suspicious_checkpoint_count += 1
                    if active_repair and self._repair_complete(task_state, active_repair):
                        active_repair = None
                    if self.history:
                        self.history.add_transition(
                            step, proposal, after, result, phase,
                            blocked_action=blocked_action)
            elif self.mode == "stateguard":
                verification_calls += 1
                try:
                    binding = (logger.bind_event(transition_event)
                               if logger else nullcontext())
                    with binding:
                        result = self.guard.verify_transition(
                            task_state, obs, proposal, after)
                    task_state.apply(result.state_updates)
                    adaptive_decision = apply_adaptive_result(
                        proposal.subgoal_id, result, step, after)
                except GuardCallBudgetExceeded as exc:
                    status, error = "guard_budget_exhausted", str(exc)
                    if logger:
                        logger.finish_event(
                            transition_event, "environment_transition", step,
                            before_state, task_state.serialize(), "failed",
                            execution_receipt=getattr(
                                env, "last_execution_receipt", None),
                            failure_type="guard_call_budget", exception=str(exc))
                    break
                except ValueError as exc:
                    status, error = "guard_parse_failed", str(exc)
                    if logger:
                        logger.finish_event(
                            transition_event, "environment_transition", step,
                            before_state, task_state.serialize(), "failed",
                            execution_receipt=getattr(
                                env, "last_execution_receipt", None),
                            failure_type="guard_parse_failure", exception=str(exc))
                    break
                except Exception as exc:
                    status, error = "model_failed", str(exc)
                    if logger:
                        logger.finish_event(
                            transition_event, "environment_transition", step,
                            before_state, task_state.serialize(), "failed",
                            execution_receipt=getattr(
                                env, "last_execution_receipt", None),
                            failure_type="model_failure", exception=str(exc))
                    break
                for update in result.state_updates:
                    if update["op"] == "stale": invalidated.update(update["node_ids"])
                    elif update["op"] == "fail": invalidated.add(update["node_id"])
                if result.fault_root:
                    roots.append(RootPredictionEvent(step, result.fault_root).to_dict())
                if result.repair:
                    contradiction_count += 1
                    repair_cycles += 1; result.repair.repair_cycle_id = repair_cycles
                    active_repair = result.repair; repairs.append(result.repair.to_dict())
                    reactivated.update(result.repair.reverify_nodes)
                    event = InterventionEvent(step, "repair_request", repair_cycles)
                    interventions.append(event.to_dict()); step_interventions.append(event)
                    if not self.budget.record(result.repair.fault_root):
                        status = "repair_failed"
                        repair_budget_exhaustions.append({
                            "fault_root": result.repair.fault_root,
                            "repair_cycle_id": repair_cycles,
                            "budget": "cycles_per_fault",
                            "limit": self.budget.limit,
                        })
                elif result.judgement == "unknown" and result.verification_target:
                    previous_action, previous_count = unknown_cycles.get(
                        proposal.subgoal_id, (None, 0))
                    count = (previous_count + 1
                             if self._same_intended_action(proposal.action, previous_action)
                             else 1)
                    unknown_cycles[proposal.subgoal_id] = (proposal.action, count)
                    if count > self.max_unknown:
                        if self.adaptive_controller is not None:
                            revision_node = proposal.subgoal_id
                            node = task_state.get(proposal.subgoal_id)
                            if node.status in {NodeStatus.EXECUTED, NodeStatus.SUSPICIOUS}:
                                task_state.mark_unverifiable(
                                    proposal.subgoal_id,
                                    "verification cycle budget exhausted")
                        else:
                            status = "verification_failed"; break
                    next_context = VerificationRequest(result.verification_target,
                                                       proposal.subgoal_id, count)
                    event = InterventionEvent(step, "verification_request")
                    interventions.append(event.to_dict()); step_interventions.append(event)
                if active_repair and self._repair_complete(task_state, active_repair):
                    active_repair = None
                if self.history:
                    self.history.add_transition(step, proposal, after, result, phase)
            elif self.mode == "latest_retry" and exposure:
                next_context = self.LATEST_RETRY_PROMPT

            if result is not None:
                if result.judgement == "unknown":
                    unknown_type = result.to_dict().get("unknown_type")
                    unknown_type_counts[unknown_type] = (
                        unknown_type_counts.get(unknown_type, 0) + 1)
                    consecutive_unknown += 1
                    max_observed_consecutive_unknown = max(
                        max_observed_consecutive_unknown, consecutive_unknown)
                    if consecutive_unknown >= self.max_consecutive_unknown:
                        status = "unknown_budget_exhausted"
                        error = ("consecutive UNKNOWN budget exhausted at "
                                 f"{self.max_consecutive_unknown}")
                else:
                    consecutive_unknown = 0

            post_action_artifact_id = (logger.record_observation(
                after, "post_action_screenshot", transition_event)
                if logger else None)
            if logger and result is not None:
                if result.judgement == "unknown":
                    logger.record_unknown(
                        transition_event, step, proposal.subgoal_id,
                        result.to_dict(), [post_action_artifact_id])
                else:
                    logger.resolve_unknowns(
                        proposal.subgoal_id,
                        "VALID" if result.judgement == "verified" else "FAILED",
                        step, [post_action_artifact_id, transition_event], "later_state")
            if logger:
                logger.log_step(step, before_state, proposal, injection, exposure, executed,
                                phase, phase_cycle_id, repair_phase,
                                obs, after, result, context, step_interventions)
                logger.finish_event(
                    transition_event, "environment_transition", step,
                    before_state, task_state.serialize(), "completed",
                    observation_after_artifact_id=post_action_artifact_id,
                    execution_receipt=getattr(env, "last_execution_receipt", None),
                    guard_result=result.to_dict() if result else None,
                    interventions=[event.to_dict() for event in step_interventions])
            trace.record_step(
                step, task_state, observation_after=after,
                checkpoint_reason=(decision.reason if sparse and result is not None else None),
                checkpoint_kind=(decision.checkpoint_kind if sparse and result is not None else None),
                execution_phase=repair_phase or phase,
                contract=(self.adaptive_controller.store.active(proposal.subgoal_id)
                          if self.adaptive_controller else None),
                guard_result=result,
                debt_update=(adaptive_decision.debt if adaptive_decision else None))
            obs = after
            if revision_node is not None:
                if attempt_local_replan(revision_node, step, obs):
                    status, error = "max_steps", None
                    continue
            if status in {"repair_failed", "plan_revision_required",
                          "plan_revision_failed", "unknown_budget_exhausted",
                          "guard_budget_exhausted"}:
                break
        else:
            step = self.max_steps

        evaluation = None
        evaluator_exception = None
        evaluator_state = task_state.serialize()
        evaluator_event = (logger.start_event(
            "evaluator", None, evaluator_state) if logger else None)
        try:
            evaluation = env.evaluate(task_spec)
            if logger:
                logger.record_evaluator(
                    result=evaluation, event_id=evaluator_event,
                    task_state=evaluator_state)
            success = bool(evaluation.success)
            environment_score = evaluation.score
            evaluator_details = evaluation.details
        except Exception as exc:
            evaluator_exception = f"{type(exc).__name__}: {exc}"
            success = False
            environment_score = 0.0
            evaluator_details = None
            status = "evaluator_failed"
            error = evaluator_exception
            if logger:
                logger.record_evaluator(
                    error=exc, event_id=evaluator_event,
                    task_state=evaluator_state)
        if logger:
            logger.close_unknowns(success, evaluator_event)
        if status == "completed" and not success: status = "task_failed"
        if success and status in {"max_steps", "stalled"}: status = "completed"
        if logger:
            logger.record_termination(
                status, error, step if "step" in locals() else None,
                task_state.serialize())
        backend = getattr(self.guard, "backend", None)
        guard_model = getattr(backend, "mllm", backend)
        grounder_model = (getattr(self.adaptive_controller.grounder, "provider", None)
                          if self.adaptive_controller else None)
        replanner_model = (getattr(self.runtime_replanner, "provider", None)
                           if self.runtime_replanner else None)
        injected_step = injections[0]["injected_step"] if injections else None
        exposed_step = exposures[0]["exposed_step"] if exposures else None
        first_root = roots[0]["fault_root"] if roots else None
        eventual_root = roots[-1]["fault_root"] if roots else None
        first_detection = roots[0]["step"] if roots else None
        ground_root = injector.spec["root_node"] if injector else None
        affected = set(injector.spec.get("expected_affected", [])) if injector else set()
        preservable = verified_before_fault - affected
        final_verified = {nid for nid, node in task_state.nodes.items()
                          if node.status == NodeStatus.VERIFIED}
        actually_preserved = preservable - invalidated - repair_targets
        actually_preserved &= final_verified
        reexecuted = preservable & repair_targets
        denominator = len(preservable)
        state_rate = len(preservable & final_verified) / denominator if denominator else 1.0
        strict_rate = len(actually_preserved) / denominator if denominator else 1.0
        certified_clean = bool(task_spec.get("certified_clean", False) and not injector)
        false_events = sum(
            event.get("intervention_type") == "repair_request"
            for event in interventions
        ) if certified_clean else 0

        result = EpisodeResult(
            status=status, success=success, total_steps=step if 'step' in locals() else 0,
            task_state=task_state, fault_events=injections, failure_exposure_events=exposures,
            repair_events=repairs, root_predictions=roots, intervention_events=interventions,
            preserved_nodes=sorted(actually_preserved), reactivated_nodes=sorted(reactivated),
            executor_calls=getattr(self.executor, "calls", 0),
            guard_calls=getattr(guard_model, "calls", 0),
            executor_tokens=getattr(self.executor, "tokens", 0),
            guard_tokens=getattr(guard_model, "tokens", 0),
            executor_latency=getattr(self.executor, "latency", 0.0),
            guard_latency=getattr(guard_model, "latency", 0.0),
            grounder_calls=getattr(grounder_model, "calls", 0),
            grounder_tokens=getattr(grounder_model, "tokens", 0),
            grounder_latency=getattr(grounder_model, "latency", 0.0),
            replanner_calls=getattr(replanner_model, "calls", 0),
            replanner_tokens=getattr(replanner_model, "tokens", 0),
            replanner_latency=getattr(replanner_model, "latency", 0.0),
            environment_score=environment_score,
            evaluator_details=evaluator_details,
            evaluator_exception=evaluator_exception, error=error,
            fault_injected_step=injected_step, failure_exposed_step=exposed_step,
            guard_first_detection_step=first_detection,
            guard_detection_delay=(first_detection - injected_step
                                   if first_detection is not None and injected_step is not None else None),
            early_detection=(first_detection is not None and
                             (exposed_step is None or first_detection < exposed_step)),
            first_root_prediction=first_root, eventual_root_prediction=eventual_root,
            first_root_accuracy=float(bool(ground_root) and first_root == ground_root),
            eventual_root_accuracy=float(bool(ground_root) and eventual_root == ground_root),
            repair_cycle_count=repair_cycles, repair_action_count=repair_actions,
            repair_budget_exhaustions=repair_budget_exhaustions,
            suspicious_checkpoint_count=suspicious_checkpoint_count,
            trace_entry_count=len(trace.storage.entries),
            preservable_nodes=sorted(preservable),
            actually_preserved_nodes=sorted(actually_preserved),
            reexecuted_preserved_nodes=sorted(reexecuted),
            state_preservation_rate=state_rate,
            strict_progress_preservation_rate=strict_rate,
            guard_intervention_count=len(interventions), certified_clean=certified_clean,
            false_intervention_episode=bool(false_events),
            false_intervention_event_count=false_events,
            fault_reexecution_observed=fault_reexecution_observed,
            frontier_violation_count=frontier_violations,
            frontier_recovery_count=frontier_recovery_count,
            checkpoint_count=checkpoint_count, checkpoint_reasons=checkpoint_reasons,
            checkpoint_kinds=checkpoint_kinds,
            verification_calls=verification_calls,
            unknown_checkpoint_count=unknown_checkpoint_count,
            contradiction_count=contradiction_count,
            premature_finish_count=premature_finish_count,
            plan_revision_count=plan_revision_count,
            local_replan_count=local_replan_count,
            local_replan_success_count=local_replan_success_count,
            executor_overclaim_count=(self.completion_claims.overclaim_count
                                      if self.completion_claims else 0),
            executor_finish_reconciliation_count=getattr(
                self.executor, "finish_reconciliation_count", 0),
            guard_parse_fail_open_count=getattr(
                guard_model, "parse_fail_open_count", 0),
            guard_strategy_normalization_count=getattr(
                guard_model, "strategy_normalization_count", 0),
            guard_progress_update_drop_count=getattr(
                guard_model, "progress_update_drop_count", 0),
            replanner_fallback_count=getattr(replanner_model, "fallback_count", 0),
            max_consecutive_unknown_observed=max_observed_consecutive_unknown,
            unknown_type_counts=unknown_type_counts,
            actions_per_subgoal=actions_per_subgoal,
            steps_between_checkpoints=steps_between_checkpoints,
            metrics=(dict(self.adaptive_controller.metrics)
                     if self.adaptive_controller else {}),
            **(dict(self.adaptive_controller.metrics)
               if self.adaptive_controller else {}))
        if logger and self.adaptive_controller is not None:
            for event in self.adaptive_controller.store.events:
                logger.append("contract_events.jsonl", event.to_dict())
                trigger = getattr(event, "trigger", None)
                trigger_value = getattr(trigger, "value", trigger)
                if trigger_value not in {None, "node_activated"}:
                    logger.record_intervention(
                        getattr(event, "step", None), "reground",
                        decision={"trigger": trigger_value,
                                  "previous_failure_reason": getattr(
                                      event, "previous_failure_reason", None)},
                        execution=event.to_dict(),
                        immediate_result={
                            "accepted": getattr(event, "accepted", None),
                            "evidence_sources_changed": getattr(
                                event, "evidence_sources_changed", None)},
                        task_state=task_state.serialize(),
                    )
        if logger: logger.finish(result)
        return result
