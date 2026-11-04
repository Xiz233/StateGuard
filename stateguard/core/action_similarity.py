from __future__ import annotations


def actions_equivalent(first, second, coordinate_tolerance: int = 75) -> bool:
    """Compare GUI actions semantically enough to detect local retry loops."""
    if not isinstance(first, dict) or not isinstance(second, dict):
        return first == second
    if first.get("type") != second.get("type"):
        return False
    kind = first.get("type")
    if kind == "click":
        return (
            first.get("button", "left") == second.get("button", "left")
            and first.get("clicks", 1) == second.get("clicks", 1)
            and _coordinates_close(first, second, ("x", "y"), coordinate_tolerance)
        )
    if kind == "drag":
        return _coordinates_close(
            first, second, ("x1", "y1", "x2", "y2"), coordinate_tolerance
        )
    if kind == "scroll":
        return _coordinates_close(first, second, ("dx", "dy"), coordinate_tolerance)
    return first == second


def _coordinates_close(first, second, keys, tolerance) -> bool:
    for key in keys:
        left, right = first.get(key), second.get(key)
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return False
        if abs(left - right) > tolerance:
            return False
    return True
