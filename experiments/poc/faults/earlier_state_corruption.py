from .base import FaultInjector


class EarlierStateCorruptionInjector(FaultInjector):
    """Corrupt an early dependency; exposure is scheduled independently."""
    def mutate_action(self, proposal, spec):
        mutation = spec["inject"]["mutation"]
        if "action_override" in mutation:
            return dict(mutation["action_override"])
        if "coordinate_offset" in mutation:
            action = dict(proposal.action)
            if action.get("type") != "click":
                raise ValueError("coordinate corruption requires a click action")
            action["x"] += mutation["coordinate_offset"].get("dx", 0)
            action["y"] += mutation["coordinate_offset"].get("dy", 0)
            return action
        if "replace_text" in mutation:
            action = dict(proposal.action)
            if action.get("type") != "type":
                raise ValueError("text corruption requires a type action")
            action["text"] = mutation["replace_text"]
            return action
        raise ValueError("earlier_state_corruption requires an explicit mutation")
