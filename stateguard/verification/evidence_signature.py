"""Contract-relevant evidence signatures and information-gain checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .contracts import EvidenceContract
from .result import EvidenceResult


@dataclass(frozen=True)
class EvidenceSignature:
    digest: str
    verifier_id: str
    sources: tuple[str, ...]
    relevant_values: dict[str, Any]
    verification_target: str | None
    progress_evidence: bool


def build_evidence_signature(
    result: EvidenceResult, contract: EvidenceContract
) -> EvidenceSignature:
    fields = set(contract.observable_fields)
    values = (
        {key: value for key, value in result.relevant_values.items() if key in fields}
        if fields
        else dict(result.relevant_values)
    )
    payload = {
        "contract_id": contract.contract_id,
        "verifier_id": result.verifier_id,
        "sources": sorted(source.value for source in result.sources),
        "relevant_values": _stable(values),
        "verification_target": result.verification_target,
        "progress_evidence": result.progress_evidence,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EvidenceSignature(
        digest,
        result.verifier_id,
        tuple(payload["sources"]),
        values,
        result.verification_target,
        result.progress_evidence,
    )


def has_information_gain(
    previous: EvidenceSignature | None,
    current: EvidenceSignature,
    contract: EvidenceContract,
) -> bool:
    if previous is None:
        return bool(current.relevant_values or current.progress_evidence)
    if current.progress_evidence and not previous.progress_evidence:
        return True
    if current.verifier_id != previous.verifier_id:
        return True
    if set(current.sources) - set(previous.sources):
        return True
    if current.relevant_values != previous.relevant_values:
        return True
    if current.verification_target != previous.verification_target:
        return True
    return False


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
