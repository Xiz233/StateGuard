from __future__ import annotations


EFFECT_OBSERVABILITY = {"visual", "structured", "persistence", "none", "auto"}

_ACTION_ALIASES = {
    "double_click": {"type": "click", "clicks": 2},
    "right_click": {"type": "click", "button": "right"},
    "middle_click": {"type": "click", "button": "middle"},
}


def canonicalize_action(action: dict) -> dict:
    """Normalize common GUI-action aliases into the runtime action contract."""
    if not isinstance(action, dict):
        return action
    normalized = dict(action)
    kind = normalized.get("type")
    if isinstance(kind, str):
        kind = kind.strip().lower().replace("-", "_").replace(" ", "_")
        normalized["type"] = kind
    alias = _ACTION_ALIASES.get(kind)
    if alias:
        normalized["type"] = alias["type"]
        for key, value in alias.items():
            if key != "type":
                normalized.setdefault(key, value)
    return normalized


def default_effect_observability(action: dict) -> str:
    """Conservative evidence channel when an older Executor omits the field."""
    kind = action.get("type") if isinstance(action, dict) else None
    if kind in {"type", "drag", "scroll"}:
        return "visual"
    if kind == "hotkey":
        keys = {str(key).lower() for key in action.get("keys", [])}
        if ("ctrl" in keys or "command" in keys) and keys & {"c", "s"}:
            return "none"
        return "visual"
    # A click may trigger a visible transition or only support visual reasoning.
    # Require the Executor to declare which one instead of guessing from prose.
    return "none"
