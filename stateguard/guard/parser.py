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
from ..core.schema import GuardResult, FaultType
from ..verification.result import EvidenceGap, EvidenceStrategy, UnknownReason
from ..verification.unknowns import classify_unknown_type

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
    """Resolve '@param' references from action kwargs; keep other literals."""
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


def parse_guard_output(data: dict | None) -> GuardResult:
    if not isinstance(data, dict):
        raise ValueError("guard output must be a JSON object")
    judgement = str(data.get("judgement", "")).lower()
    judgement = {
        "correct": "verified",
        "incorrect": "contradicted",
        "uncertain": "unknown",
    }.get(judgement, judgement)
    if judgement not in {"verified", "contradicted", "unknown"}:
        raise ValueError(f"invalid guard judgement {judgement!r}")
    updates = data.get("progress_updates", [])
    if not isinstance(updates, list):
        raise ValueError("progress_updates must be a list")
    root, fault = data.get("fault_root"), data.get("fault_type")
    if judgement == "contradicted":
        if not root or fault not in {item.value for item in FaultType}:
            raise ValueError("contradiction requires valid fault_root and fault_type")
    unknown_reason = data.get("unknown_reason")
    if judgement == "unknown":
        unknown_reason = unknown_reason or UnknownReason.NEED_MORE_EVIDENCE.value
        try:
            unknown_reason = UnknownReason(unknown_reason).value
        except ValueError as exc:
            raise ValueError(f"invalid unknown_reason {unknown_reason!r}") from exc
    elif unknown_reason is not None:
        raise ValueError("unknown_reason is only valid for UNKNOWN")
    gap = _parse_evidence_gap(data.get("evidence_gap"))
    unknown_type = classify_unknown_type({**data, "evidence_gap": gap}) \
        if judgement == "unknown" else None
    return GuardResult(
        judgement, progress_updates=updates, fault_root=root, fault_type=fault,
        verification_target=data.get("verification_target"),
        reason=str(data.get("reason", "")), unknown_reason=unknown_reason,
        unknown_type=unknown_type, evidence_gap=gap,
        active_contract_id=data.get("active_contract_id"))


def _parse_evidence_gap(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("evidence_gap must be an object")
    attempted = value.get("attempted_strategy")
    recommended = value.get("recommended_strategy")
    attempted_value = _normalise_evidence_strategy(attempted)
    recommended_value = _normalise_evidence_strategy(recommended)
    gap = EvidenceGap(
        missing_evidence=_string_tuple(value.get("missing_evidence")),
        available_evidence=_string_tuple(value.get("available_evidence")),
        unavailable_evidence=_string_tuple(value.get("unavailable_evidence")),
        attempted_strategy=attempted_value,
        recommended_strategy=recommended_value,
        requires_new_source=bool(value.get("requires_new_source", False)),
        same_contract=bool(value.get("same_contract", True)),
    )
    parsed = {
        "missing_evidence": list(gap.missing_evidence),
        "available_evidence": list(gap.available_evidence),
        "unavailable_evidence": list(gap.unavailable_evidence),
        "attempted_strategy": gap.attempted_strategy.value if gap.attempted_strategy else None,
        "recommended_strategy": (
            gap.recommended_strategy.value if gap.recommended_strategy else None),
        "requires_new_source": gap.requires_new_source,
        "same_contract": gap.same_contract,
    }
    if attempted and (attempted_value is None
                      or str(attempted).strip().lower() != attempted_value.value):
        parsed["raw_attempted_strategy"] = str(attempted)
    if recommended and (recommended_value is None
                        or str(recommended).strip().lower() != recommended_value.value):
        parsed["raw_recommended_strategy"] = str(recommended)
    return parsed


def _string_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _normalise_evidence_strategy(value) -> EvidenceStrategy | None:
    if not value:
        return None
    text = str(value).strip().lower()
    try:
        return EvidenceStrategy(text)
    except ValueError:
        pass
    rules = (
        (("accessibility", "a11y"), EvidenceStrategy.ACQUIRE_ACCESSIBILITY_EVIDENCE),
        (("structured", "dom", "application state"),
         EvidenceStrategy.ACQUIRE_STRUCTURED_EVIDENCE),
        (("persist", "save", "reopen"), EvidenceStrategy.PERSISTENCE_RECHECK),
        (("external", "clipboard", "copy", "url", "query"),
         EvidenceStrategy.EXTERNAL_STATE_QUERY),
        (("scroll", "wait", "navigate", "open", "click", "right-click", "tab"),
         EvidenceStrategy.NAVIGATE_TO_OBSERVABLE_STATE),
        (("visual", "screenshot", "inspect", "look"),
         EvidenceStrategy.ACQUIRE_VISUAL_EVIDENCE),
    )
    return next((strategy for needles, strategy in rules
                 if any(needle in text for needle in needles)), None)
