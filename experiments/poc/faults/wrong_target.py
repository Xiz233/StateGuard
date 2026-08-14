from .base import FaultInjector


class WrongTargetInjector(FaultInjector):
    def mutate_action(self, proposal, spec):
        return dict(spec["inject"]["mutation"]["action_override"])
