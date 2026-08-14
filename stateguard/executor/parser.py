from dataclasses import dataclass

from stateguard.core.schema import ActionProposal


ACTION_FIELDS = {
    "click": {"x", "y"}, "type": {"text"}, "hotkey": {"keys"},
    "scroll": {"dx", "dy"}, "drag": {"x1", "y1", "x2", "y2"}, "wait": set(),
}


@dataclass(frozen=True)
class ActionBounds:
    width: int
    height: int


def validate_action(action: dict, bounds: ActionBounds | None = None) -> dict:
    kind = action.get("type") if isinstance(action, dict) else None
    if kind not in ACTION_FIELDS or not ACTION_FIELDS[kind] <= action.keys():
        raise ValueError(f"invalid executor action {action!r}")
    allowed = ACTION_FIELDS[kind] | {"type"}
    if set(action) - allowed:
        raise ValueError(f"unexpected fields for {kind}: {sorted(set(action) - allowed)}")
    if bounds:
        for key in ({"x", "x1", "x2"} & action.keys()):
            if not 0 <= action[key] < bounds.width:
                raise ValueError(f"{key} outside screen bounds")
        for key in ({"y", "y1", "y2"} & action.keys()):
            if not 0 <= action[key] < bounds.height:
                raise ValueError(f"{key} outside screen bounds")
    return dict(action)


def parse_executor_output(data: dict, bounds: ActionBounds | None = None) -> ActionProposal:
    required = {"subgoal_id", "intent", "expected_effect", "action", "is_finish"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError("executor output is missing required fields")
    action = data["action"]
    if not data["is_finish"]:
        action = validate_action(action, bounds)
    return ActionProposal(data["subgoal_id"], action, data["intent"],
                          data["expected_effect"], bool(data["is_finish"]))
