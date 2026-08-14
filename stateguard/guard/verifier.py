"""Rule-based transition verifier (指引.txt §5.1).

Decides VERIFIED / CONTRADICTED / UNKNOWN:
- effect-mode nodes are checked right after the action;
- persistence-mode nodes are UNKNOWN until a verify_action (e.g. reopen)
  re-runs and confirms the effect.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.schema import Evidence, TaskNode
from ..interfaces.observation import Observation
from ..interfaces.action import Action
from .parser import resolve_effect, check_effect


@dataclass
class Verdict:
    judgement: str  # verified | contradicted | unknown
    verification_target: str | None = None
    evidence: Evidence | None = None


def verify_transition(node: TaskNode, proposal, before: Observation,
                      after: Observation) -> Verdict:
    action: Action = proposal.action
    persist = bool(getattr(node, "verify_action", None))
    reopening = persist and getattr(action, "name", None) == node.verify_action

    params = action.get("params", action) if isinstance(action, dict) else action.params
    effect = resolve_effect(node.expected_effect, params)
    result = check_effect(effect, after.snapshot)

    if persist and not reopening:
        # EXECUTED but effect unconfirmed -> UNKNOWN + verification target (§20)
        return Verdict(
            "unknown",
            verification_target=(
                f"Re-run {node.verify_action} to confirm persistence of {node.description}."
            ),
        )

    if result == "matched":
        detail = "; ".join(f"{v}={val!r}" for v, val in effect.items())
        return Verdict(
            "verified",
            evidence=Evidence(
                step_id=after.step,
                source="verifier",
                description=f"{node.description} confirmed ({detail})",
                confidence=0.9,
                observation_ref=after.ref,
            ),
        )

    if persist:
        return Verdict("contradicted",
                       verification_target=f"{node.verify_action} could not confirm {node.description}")

    if result == "unknown":
        return Verdict("unknown",
                       verification_target=f"cannot confirm {node.description} from observation")

    return Verdict("contradicted",
                   verification_target=f"{node.description} effect not present in observation")
