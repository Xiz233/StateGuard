from dataclasses import dataclass

from stateguard.core.action_capabilities import (
    EFFECT_OBSERVABILITY, canonicalize_action, default_effect_observability,
)
from stateguard.core.schema import ActionProposal


ACTION_REQUIRED_FIELDS = {
    "click": {"x", "y"}, "type": {"text"}, "hotkey": {"keys"},
    "scroll": {"dx", "dy"}, "drag": {"x1", "y1", "x2", "y2"}, "wait": set(),
}
ACTION_OPTIONAL_FIELDS = {
    "click": {"button", "clicks"},
}


@dataclass(frozen=True)
class ActionBounds:
    width: int
    height: int


def validate_action(action: dict, bounds: ActionBounds | None = None) -> dict:
    action = canonicalize_action(action)
    kind = action.get("type") if isinstance(action, dict) else None
    if kind not in ACTION_REQUIRED_FIELDS \
            or not ACTION_REQUIRED_FIELDS[kind] <= action.keys():
        raise ValueError(f"invalid executor action {action!r}")
    allowed = ACTION_REQUIRED_FIELDS[kind] | ACTION_OPTIONAL_FIELDS.get(kind, set()) | {"type"}
    if set(action) - allowed:
        raise ValueError(f"unexpected fields for {kind}: {sorted(set(action) - allowed)}")
    if kind == "click":
        button, clicks = action.get("button", "left"), action.get("clicks", 1)
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"invalid click button {button!r}")
        if not isinstance(clicks, int) or not 1 <= clicks <= 3:
            raise ValueError("clicks must be an integer from 1 to 3")
    if bounds:
        for key in ({"x", "x1", "x2"} & action.keys()):
            if not 0 <= action[key] < bounds.width:
                raise ValueError(f"{key} outside screen bounds")
        for key in ({"y", "y1", "y2"} & action.keys()):
            if not 0 <= action[key] < bounds.height:
                raise ValueError(f"{key} outside screen bounds")
    return dict(action)


def parse_executor_output(data: dict, bounds: ActionBounds | None = None) -> ActionProposal:
    data = normalize_executor_output(data)
    required = {"subgoal_id", "intent", "expected_effect", "action", "is_finish"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError("executor output is missing required fields")
    action = data["action"]
    if not data["is_finish"]:
        action = validate_action(action, bounds)
    observability = data.get("effect_observability", "auto")
    if observability not in EFFECT_OBSERVABILITY:
        raise ValueError(f"invalid effect_observability {observability!r}")
    if observability == "auto":
        observability = default_effect_observability(action)
    return ActionProposal(data["subgoal_id"], action, data["intent"],
                          data["expected_effect"],
                          bool(data.get("subgoal_done", False)),
                          bool(data["is_finish"]), observability)


def normalize_executor_output(data):
    """Normalize common wrappers/aliases without inventing an action."""
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        return data
    for key in ("proposal", "action_proposal", "executor_output", "result", "output"):
        if isinstance(data.get(key), dict):
            data = data[key]
            break
    data = dict(data)
    aliases = {
        "subgoal": "subgoal_id",
        "goal_id": "subgoal_id",
        "expected_result": "expected_effect",
        "finish": "is_finish",
        "done": "subgoal_done",
    }
    for source, target in aliases.items():
        if target not in data and source in data:
            data[target] = data[source]
    if "intent" not in data and isinstance(data.get("action"), dict):
        data["intent"] = str(data.get("description") or data["action"].get("type") or "act")
    return data
