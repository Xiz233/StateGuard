from .base import FaultInjector


class WrongValueInjector(FaultInjector):
    def mutate_action(self, proposal, spec):
        action = dict(proposal.action)
        action["text"] = spec["inject"]["mutation"]["replace_text"]
        return action
