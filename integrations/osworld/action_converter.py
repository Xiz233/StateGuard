from __future__ import annotations

from stateguard.executor.parser import ACTION_FIELDS


def convert_action(action: dict) -> dict:
    kind = action.get("type") if isinstance(action, dict) else None
    if kind not in ACTION_FIELDS or not ACTION_FIELDS[kind] <= action.keys():
        raise ValueError(f"unsupported OSWorld action {action!r}")
    return dict(action)
