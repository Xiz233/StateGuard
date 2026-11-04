"""Stable taxonomy for inconclusive verification outcomes."""

from __future__ import annotations

from enum import Enum


class UnknownType(str, Enum):
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    VERIFICATION_TARGET_UNCLEAR = "verification_target_unclear"
    HIDDEN_OR_PERSISTENT_STATE = "hidden_or_persistent_state"
    CONTRACT_UNVERIFIABLE = "contract_unverifiable"
    GUARD_CAPABILITY_INSUFFICIENT = "guard_capability_insufficient"
    ENVIRONMENT_STATE_MISSING = "environment_state_missing"


def classify_unknown_type(value: dict) -> str:
    explicit = str(value.get("unknown_type") or "").strip().lower()
    aliases = {
        "insufficient_evidence": UnknownType.EVIDENCE_INSUFFICIENT.value,
        "evidence_missing": UnknownType.EVIDENCE_INSUFFICIENT.value,
        "unclear_target": UnknownType.VERIFICATION_TARGET_UNCLEAR.value,
        "persistent_state": UnknownType.HIDDEN_OR_PERSISTENT_STATE.value,
        "hidden_state": UnknownType.HIDDEN_OR_PERSISTENT_STATE.value,
        "unverifiable_contract": UnknownType.CONTRACT_UNVERIFIABLE.value,
        "guard_inconclusive": UnknownType.GUARD_CAPABILITY_INSUFFICIENT.value,
        "missing_environment_state": UnknownType.ENVIRONMENT_STATE_MISSING.value,
    }
    explicit = aliases.get(explicit, explicit)
    if explicit in {item.value for item in UnknownType}:
        return explicit

    reason_code = str(value.get("unknown_reason") or "").lower()
    reason = str(value.get("reason") or "").lower()
    target = str(value.get("verification_target") or "").strip()
    gap = value.get("evidence_gap") or {}
    missing = " ".join(str(item) for item in gap.get("missing_evidence", ())).lower()
    unavailable = " ".join(
        str(item) for item in gap.get("unavailable_evidence", ())).lower()
    available = gap.get("available_evidence") or ()
    text = " ".join((reason, target.lower(), missing, unavailable))

    if not target or target.lower() in {"unknown", "inspect", "verify", "retry"}:
        return UnknownType.VERIFICATION_TARGET_UNCLEAR.value
    if reason_code in {"contract_stale", "node_unverifiable"}:
        return UnknownType.CONTRACT_UNVERIFIABLE.value
    if any(word in text for word in (
            "persist", "saved", "reopen", "disk", "hidden", "private state")):
        return UnknownType.HIDDEN_OR_PERSISTENT_STATE.value
    if reason_code == "source_unavailable" or any(word in text for word in (
            "accessibility", "a11y", "structured state", "environment state",
            "metadata", "unavailable source")):
        return UnknownType.ENVIRONMENT_STATE_MISSING.value
    if reason_code == "verifier_inconclusive" or (available and not missing):
        return UnknownType.GUARD_CAPABILITY_INSUFFICIENT.value
    if available and any(phrase in reason for phrase in (
            "positively shows", "visible", "after image shows", "screenshot shows")):
        return UnknownType.GUARD_CAPABILITY_INSUFFICIENT.value
    return UnknownType.EVIDENCE_INSUFFICIENT.value
