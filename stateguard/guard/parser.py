"""Tiny observation predicate / expected-effect parser (rule-based, Phase I).

Predicate grammar (expected_result / expected_effect):
    "var == value" | "var != value" | "var set" | "var unset"
Expected-effect dict: { "var.path": value | "@param" } compared against
the post-action observation snapshot.
"""

from __future__ import annotations

import re
from typing import Any

from ..interfaces.observation import get_path

_PRED = re.compile(r"^([A-Za-z_][\w.]*)\s*(==|!=)\s*(.+)$")
_SET = re.compile(r"^([A-Za-z_][\w.]*)\s+(set|unset)$")


def parse_predicate(pred: str) -> tuple[str, str, Any] | None:
    m = _PRED.match(pred.strip())
    if m:
        return m.group(1), m.group(2), _parse_literal(m.group(3))
    m = _SET.match(pred.strip())
    if m:
        return m.group(1), m.group(2), None
    return None


def _parse_literal(s: str) -> Any:
    s = s.strip().strip("'\"")
    if s == "True":
        return True
    if s == "False":
        return False
    if s == "None":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def predicate_holds(pred: str, snapshot: dict) -> bool | None:
    """None = cannot evaluate (missing var or unparseable predicate)."""
    parsed = parse_predicate(pred)
    if parsed is None:
        return None
    var, op, val = parsed
    actual = get_path(snapshot, var)
    if op == "==":
        return actual is not None and actual == val
    if op == "!=":
        return actual is not None and actual != val
    if op == "set":
        return actual is not None
    return actual is None  # "unset"


def predicate_violated(pred: str, snapshot: dict) -> bool:
    return predicate_holds(pred, snapshot) is False


def resolve_effect(effect: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    """'@param' placeholders resolved from action kwargs; others are literals."""
    resolved = {}
    for var, expr in effect.items():
        if isinstance(expr, str) and expr.startswith("@"):
            resolved[var] = params[expr[1:]]
        else:
            resolved[var] = _parse_literal(str(expr)) if isinstance(expr, str) else expr
    return resolved


def check_effect(resolved: dict[str, Any], snapshot: dict) -> str:
    """Returns 'matched' | 'missing' | 'mismatch'."""
    if not resolved:
        return "unknown"
    for var, expected in resolved.items():
        actual = get_path(snapshot, var)
        if actual is None:
            return "missing"
        if actual != expected:
            return "mismatch"
    return "matched"
