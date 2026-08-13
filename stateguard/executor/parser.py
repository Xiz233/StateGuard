from stateguard.core.schema import ActionProposal


ACTION_FIELDS = {
    "click": {"x", "y"}, "type": {"text"}, "hotkey": {"keys"},
    "scroll": {"dx", "dy"}, "drag": {"x1", "y1", "x2", "y2"}, "wait": set(),
}


def parse_executor_output(data: dict) -> ActionProposal:
    required = {"subgoal_id", "intent", "expected_effect", "action", "is_finish"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError("executor output is missing required fields")
    action = data["action"]
    action_type = action.get("type") if isinstance(action, dict) else None
    if not data["is_finish"]:
        if action_type not in ACTION_FIELDS or not ACTION_FIELDS[action_type] <= action.keys():
            raise ValueError(f"invalid executor action {action!r}")
    return ActionProposal(data["subgoal_id"], action, data["intent"],
                          data["expected_effect"], bool(data["is_finish"]))
