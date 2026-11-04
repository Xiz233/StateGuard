from .base import FaultInjector


class WrongTargetInjector(FaultInjector):
    def mutate_action(self, proposal, spec):
        mutation = spec["inject"]["mutation"]
        if "action_override" in mutation:
            return dict(mutation["action_override"])
        action = dict(proposal.action)
        offset = mutation["coordinate_offset"]
        if action.get("type") == "click":
            action["x"] += offset.get("dx", 0)
            action["y"] += offset.get("dy", 0)
            return action
        if action.get("type") == "drag":
            for key in ("x1", "x2"):
                action[key] += offset.get("dx", 0)
            for key in ("y1", "y2"):
                action[key] += offset.get("dy", 0)
            return action
        raise ValueError("wrong_target coordinate_offset requires click or drag action")
