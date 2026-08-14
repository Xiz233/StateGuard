from __future__ import annotations

from abc import ABC, abstractmethod

from .result import FailureExposureEvent, FaultInjectionEvent


class FaultInjector(ABC):
    def __init__(self, spec: dict):
        self.spec, self.injected, self.exposed = spec, False, False
        exposure = dict(spec.get("exposure", {}))
        if not exposure:
            exposure = {"mode": "immediate" if spec.get("detection", {}).get("immediate", True)
                        else "delayed"}
        self.exposure = exposure
        if self.exposure.get("mode") not in {"immediate", "delayed", "latent"}:
            raise ValueError(f"invalid exposure mode {self.exposure.get('mode')!r}")
        self.injection_event: FaultInjectionEvent | None = None

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
        self.injection_event = FaultInjectionEvent(
            self.spec["fault_id"], self.spec["type"], step, self.spec["root_node"],
            proposal.to_dict(), action)
        return action, self.injection_event

    def poll_exposure(self, step, proposal) -> FailureExposureEvent | None:
        if not self.injected or self.exposed:
            return None
        mode, trigger = self.exposure["mode"], self.exposure.get("trigger", {})
        ready = mode == "immediate" and step == self.injection_event.injected_step
        if mode in {"delayed", "latent"}:
            ready = ((trigger.get("subgoal_id") is not None
                      and proposal.subgoal_id == trigger["subgoal_id"])
                     or (trigger.get("step") is not None and step >= int(trigger["step"])))
        if not ready:
            return None
        self.exposed = True
        return FailureExposureEvent(self.spec["fault_id"], step, mode, proposal.subgoal_id)

    def record_ground_truth(self): return dict(self.spec)
