from __future__ import annotations

from stateguard.executor.parser import ActionBounds, validate_action


def convert_action(action: dict, screen_size: tuple[int, int] | None = None) -> dict:
    bounds = ActionBounds(*screen_size) if screen_size else None
    return validate_action(action, bounds)
