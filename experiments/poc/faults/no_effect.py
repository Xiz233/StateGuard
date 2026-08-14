from .base import FaultInjector


class NoEffectInjector(FaultInjector):
    def mutate_action(self, proposal, spec):
        return {"type": "wait"}
