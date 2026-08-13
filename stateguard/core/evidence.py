"""Evidence helpers. Rule: every VERIFIED node must carry >= 1 Evidence
(指引.txt §8); enforcement lives in task_state.mark_verified."""

from __future__ import annotations

from .schema import Evidence


def make_evidence(step_id: int, description: str, confidence: float,
                  observation_ref: str | None = None,
                  source: str = "verifier") -> Evidence:
    return Evidence(
        step_id=step_id,
        source=source,
        description=description,
        confidence=confidence,
        observation_ref=observation_ref,
    )
