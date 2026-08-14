from __future__ import annotations

from abc import ABC, abstractmethod

from .result import FaultEvent


class FaultInjector(ABC):
    def __init__(self, spec: dict):
        self.spec, self.injected = spec, False

    def should_inject(self, task_id, step, proposal, task_state) -> bool:
        trigger = self.spec["inject"]["trigger"]
        return (not self.injected and proposal.subgoal_id == trigger["subgoal_id"]
                and step >= int(trigger.get("occurrence", 1)))

    @abstractmethod
    def mutate_action(self, proposal, spec): ...

    def inject(self, task_id, step, proposal, task_state):
        if not self.should_inject(task_id, step, proposal, task_state):
            return proposal.action, None
        action = self.mutate_action(proposal, self.spec)
        self.injected = True
        event = FaultEvent(self.spec["fault_id"], self.spec["type"], step,
                           self.spec["root_node"], proposal.to_dict(), action)
        return action, event

    def record_ground_truth(self):
        return dict(self.spec)
