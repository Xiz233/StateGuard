from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..core.schema import NodeStatus, RepairRequest, VerificationRequest
from .events import InterventionEvent, RootPredictionEvent
from .repair_loop import RepairBudget


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
    environment_score: float = 0.0
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
    preservable_nodes: list = field(default_factory=list)
    actually_preserved_nodes: list = field(default_factory=list)
    reexecuted_preserved_nodes: list = field(default_factory=list)
    state_preservation_rate: float = 1.0
    strict_progress_preservation_rate: float = 1.0
    guard_intervention_count: int = 0
    certified_clean: bool = False
    false_intervention_episode: bool = False
    false_intervention_event_count: int = 0
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
                 mode="stateguard", history=None):
        self.executor, self.guard, self.max_steps = executor, guard, max_total_steps
        self.mode, self.history = mode, history
        self.budget = RepairBudget(max_repair_cycles_per_fault)
        self.max_unknown = max_unknown_verification_cycles

    def run(self, env, task_state, task_spec=None, task_id="task", injector=None, logger=None):
        task_spec = task_spec or {}
        injections, exposures, repairs, roots, interventions = [], [], [], [], []
        invalidated, repair_targets, verified_before_fault = set(), set(), set()
        reactivated, unknown_cycles = set(), {}
        active_repair = next_context = None
        repair_cycles = repair_actions = 0
        obs, status, error = env.reset(task_spec), "max_steps", None

        for step in range(1, self.max_steps + 1):
            context = active_repair or next_context
            phase = ("repair" if active_repair else
                     "verification" if isinstance(next_context, VerificationRequest) else "normal")
            phase_cycle_id = getattr(active_repair, "repair_cycle_id", None)
            next_context = None
            try:
                proposal = self.executor.act(obs, task_state, context)
            except ValueError as exc:
                status, error = "executor_parse_failed", str(exc); break
            except Exception as exc:
                status, error = "model_failed", str(exc); break
            if proposal is None:
                status = "stalled"; break
            step_interventions = []
            if proposal.is_finish:
                if self.mode != "stateguard": status = "completed"; break
                result = self.guard.verify_finish(task_state, obs)
                if result.approved: status = "completed"; break
                event = InterventionEvent(step, "finish_rejection")
                interventions.append(event.to_dict()); step_interventions.append(event)
                if result.repair:
                    repair_cycles += 1; result.repair.repair_cycle_id = repair_cycles
                    active_repair = result.repair; repairs.append(result.repair.to_dict())
                continue

            before_state, original = task_state.serialize(), proposal.action
            executed, injection = (injector.inject(task_id, step, proposal, task_state)
                                   if injector else (original, None))
            if injection:
                verified_before_fault = {nid for nid, node in task_state.nodes.items()
                                         if node.status == NodeStatus.VERIFIED}
                injections.append(injection.to_dict())
                if hasattr(env, "note_fault_injection"):
                    env.note_fault_injection(injection, injector.spec)
            if phase == "repair":
                repair_actions += 1; repair_targets.add(proposal.subgoal_id)
            try:
                after = env.step(executed)
            except Exception as exc:
                status, error = "environment_failed", str(exc); break
            exposure = injector.poll_exposure(step, proposal) if injector else None
            if exposure:
                exposures.append(exposure.to_dict())
                if hasattr(env, "expose_failure"):
                    after = env.expose_failure(exposure)

            result = None
            if self.mode == "stateguard":
                try:
                    result = self.guard.verify_transition(task_state, obs, proposal, after)
                    task_state.apply(result.state_updates)
                except ValueError as exc:
                    status, error = "guard_parse_failed", str(exc); break
                for update in result.state_updates:
                    if update["op"] == "stale": invalidated.update(update["node_ids"])
                    elif update["op"] == "fail": invalidated.add(update["node_id"])
                if result.fault_root:
                    roots.append(RootPredictionEvent(step, result.fault_root).to_dict())
                if result.repair:
                    repair_cycles += 1; result.repair.repair_cycle_id = repair_cycles
                    active_repair = result.repair; repairs.append(result.repair.to_dict())
                    reactivated.update(result.repair.reverify_nodes)
                    event = InterventionEvent(step, "repair_request", repair_cycles)
                    interventions.append(event.to_dict()); step_interventions.append(event)
                    if not self.budget.record(result.repair.fault_root):
                        status = "repair_failed"; break
                elif result.judgement == "unknown" and result.verification_target:
                    count = unknown_cycles.get(proposal.subgoal_id, 0) + 1
                    unknown_cycles[proposal.subgoal_id] = count
                    if count > self.max_unknown:
                        status = "verification_failed"; break
                    next_context = VerificationRequest(result.verification_target,
                                                       proposal.subgoal_id, count)
                    event = InterventionEvent(step, "verification_request")
                    interventions.append(event.to_dict()); step_interventions.append(event)
                if active_repair and all(task_state.get(nid).status == NodeStatus.VERIFIED
                                         for nid in active_repair.reverify_nodes):
                    active_repair = None
                if self.history: self.history.add_transition(step, proposal, after, result)
            elif self.mode == "latest_retry" and exposure:
                next_context = self.LATEST_RETRY_PROMPT

            if logger:
                logger.log_step(step, before_state, proposal, injection, exposure, executed,
                                phase, phase_cycle_id,
                                obs, after, result, context, step_interventions)
            obs = after
        else:
            step = self.max_steps

        evaluation = env.evaluate(task_spec); success = bool(evaluation.success)
        if status == "completed" and not success: status = "task_failed"
        if success and status in {"max_steps", "stalled"}: status = "completed"
        backend = getattr(self.guard, "backend", None)
        guard_model = getattr(backend, "mllm", backend)
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
        false_events = len(interventions) if certified_clean else 0

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
            environment_score=evaluation.score, error=error,
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
            preservable_nodes=sorted(preservable),
            actually_preserved_nodes=sorted(actually_preserved),
            reexecuted_preserved_nodes=sorted(reexecuted),
            state_preservation_rate=state_rate,
            strict_progress_preservation_rate=strict_rate,
            guard_intervention_count=len(interventions), certified_clean=certified_clean,
            false_intervention_episode=bool(false_events),
            false_intervention_event_count=false_events)
        if logger: logger.finish(result)
        return result
