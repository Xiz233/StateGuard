from dataclasses import dataclass

from .repair_loop import RepairBudget


@dataclass
class EpisodeResult:
    status: str
    steps: int
    task_state: object


class EpisodeRunner:
    def __init__(self, executor, guard, max_total_steps=50, max_repair_cycles_per_fault=3):
        self.executor, self.guard, self.max_steps = executor, guard, max_total_steps
        self.budget = RepairBudget(max_repair_cycles_per_fault)

    def run(self, env, task_state):
        obs, repair = env.reset(), None
        for step in range(1, self.max_steps + 1):
            proposal = self.executor.act(obs, task_state, repair)
            if proposal is None:
                return EpisodeResult("stalled", step - 1, task_state)
            if proposal.is_finish:
                result = self.guard.verify_finish(task_state, obs)
                if result.approved:
                    return EpisodeResult("completed", step - 1, task_state)
            else:
                after = env.step(proposal.action)
                result = self.guard.verify_transition(task_state, obs, proposal, after)
                task_state.apply(result.state_updates)
                obs = after
            repair = result.repair if result.requires_repair else None
            if repair and not self.budget.record(repair.fault_root):
                return EpisodeResult("repair_failed", step, task_state)
        return EpisodeResult("max_steps", self.max_steps, task_state)
