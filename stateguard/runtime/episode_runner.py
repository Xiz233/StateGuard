from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..core.schema import VerificationRequest
from .repair_loop import RepairBudget


@dataclass
class EpisodeResult:
    status: str
    success: bool
    total_steps: int
    task_state: object
    fault_events: list = field(default_factory=list)
    repair_events: list = field(default_factory=list)
    root_predictions: list = field(default_factory=list)
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
    metrics: dict = field(default_factory=dict)

    @property
    def steps(self): return self.total_steps
    def to_dict(self):
        value = asdict(self)
        value["task_state"] = self.task_state.serialize()
        return value


class EpisodeRunner:
    def __init__(self, executor, guard=None, max_total_steps=50,
                 max_repair_cycles_per_fault=3, max_unknown_verification_cycles=3,
                 mode="stateguard", history=None):
        self.executor, self.guard, self.max_steps = executor, guard, max_total_steps
        self.mode, self.history = mode, history
        self.budget = RepairBudget(max_repair_cycles_per_fault)
        self.max_unknown = max_unknown_verification_cycles

    def run(self, env, task_state, task_spec=None, task_id="task", injector=None, logger=None):
        fault_events, repairs, roots, preserved, reactivated = [], [], [], [], []
        repair, unknown_cycles, obs = None, {}, env.reset(task_spec)
        status, error = "max_steps", None
        for step in range(1, self.max_steps + 1):
            try:
                proposal = self.executor.act(obs, task_state, repair)
            except ValueError as exc:
                status, error = "executor_parse_failed", str(exc); break
            except Exception as exc:
                status, error = "model_failed", str(exc); break
            if proposal is None:
                status = "stalled"; break
            if proposal.is_finish:
                if self.mode == "stateguard":
                    result = self.guard.verify_finish(task_state, obs)
                    if result.approved:
                        status = "completed"; break
                    repair = result.repair
                    if repair: repairs.append(repair.to_dict())
                    continue
                status = "completed"; break

            original = proposal.action
            executed, fault_event = (injector.inject(task_id, step, proposal, task_state)
                                     if injector else (original, None))
            if fault_event:
                fault_events.append(fault_event.to_dict())
            before_state = task_state.serialize()
            try:
                after = env.step(executed)
            except Exception as exc:
                status, error = "environment_failed", str(exc); break
            result = None
            if self.mode == "stateguard":
                try:
                    result = self.guard.verify_transition(task_state, obs, proposal, after)
                    task_state.apply(result.state_updates)
                except ValueError as exc:
                    status, error = "guard_parse_failed", str(exc); break
                repair = result.repair if result.requires_repair else None
                if result.fault_root: roots.append(result.fault_root)
                if repair:
                    repairs.append(repair.to_dict()); preserved += repair.preserve_nodes
                    reactivated += repair.reverify_nodes
                    if not self.budget.record(repair.fault_root):
                        status = "repair_failed"; break
                elif result.judgement == "unknown" and result.verification_target:
                    count = unknown_cycles.get(proposal.subgoal_id, 0) + 1
                    unknown_cycles[proposal.subgoal_id] = count
                    if count > self.max_unknown:
                        status = "verification_failed"; break
                    repair = VerificationRequest(result.verification_target,
                                                 proposal.subgoal_id, count)
                if self.history:
                    self.history.add_transition(step, proposal, after, result)
            elif self.mode == "latest_retry" and fault_event:
                repair = "The latest operation may not have achieved its intended effect. " \
                         "Inspect the current state and retry or revise the most recent operation."
            else:
                repair = None
            if logger:
                logger.log_step(step, before_state, proposal, fault_event, executed,
                                obs, after, result, repair)
            obs = after
        else:
            step = self.max_steps

        evaluation = env.evaluate(task_spec)
        success = bool(evaluation.success)
        if status == "completed" and not success: status = "task_failed"
        if success and status in {"max_steps", "stalled"}: status = "completed"
        backend = getattr(self.guard, "backend", None)
        guard_model = getattr(backend, "mllm", backend)
        result = EpisodeResult(status, success, step if 'step' in locals() else 0, task_state,
            fault_events, repairs, roots, sorted(set(preserved)), sorted(set(reactivated)),
            getattr(self.executor, "calls", 0), getattr(guard_model, "calls", 0),
            getattr(self.executor, "tokens", 0), getattr(guard_model, "tokens", 0),
            getattr(self.executor, "latency", 0.0), getattr(guard_model, "latency", 0.0),
            evaluation.score, error)
        if logger: logger.finish(result)
        return result
