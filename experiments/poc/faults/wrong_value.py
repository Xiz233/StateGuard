from .base import FaultInjector


class WrongValueInjector(FaultInjector):
    def mutate_action(self, proposal, spec):
        action = dict(proposal.action)
        if action.get("type") != "type":
            raise ValueError("wrong_value requires a type action")
        action["text"] = spec["inject"]["mutation"]["replace_text"]
        return action
