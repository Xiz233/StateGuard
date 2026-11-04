from __future__ import annotations

from .models import ExecutionTraceEntry
from .storage import TraceStorage
from .summarizer import summarize_observation


class TraceCollector:
    def __init__(self, storage: TraceStorage | None = None,
                 keep_recent_images: int = 10):
        self.storage = storage or TraceStorage()
        self.keep_recent_images = max(0, int(keep_recent_images))
        self._pending: dict[int, ExecutionTraceEntry] = {}

    @staticmethod
    def _trust_snapshot(task_state) -> dict[str, float]:
        return {nid: node.trust_score for nid, node in task_state.nodes.items()}

    def record_step(self, step_id: int, task_state, proposal=None,
                    executed_action=None,
                    observation_before=None, observation_after=None,
                    checkpoint_reason=None, checkpoint_kind=None,
                    execution_phase="normal", contract=None,
                    resolved_observability=None, capabilities=None,
                    guard_result=None, debt_update=None) -> ExecutionTraceEntry:
        if proposal is not None:
            entry = ExecutionTraceEntry(
                step_id=step_id,
                active_node_id=proposal.subgoal_id,
                executor_intent=proposal.intent,
                action=executed_action if executed_action is not None else proposal.action,
                expected_effect=proposal.expected_effect,
                effect_observability=getattr(
                    proposal, "effect_observability", "auto"),
                proposed_action=proposal.action,
                observation_before_summary=summarize_observation(observation_before),
                state_before=task_state.serialize(),
                trust_snapshot=self._trust_snapshot(task_state),
                execution_phase=execution_phase,
                declared_observability=getattr(
                    proposal, "effect_observability", "auto"),
                resolved_observability=(
                    resolved_observability.__dict__.copy()
                    if hasattr(resolved_observability, "__dict__")
                    else resolved_observability),
                active_contract_id=getattr(contract, "contract_id", None),
                contract_version=getattr(contract, "version", None),
                evidence_sources_available=tuple(
                    sorted(source.value for source in capabilities.available_sources))
                    if capabilities else (),
                subgoal_done=bool(getattr(proposal, "subgoal_done", False)),
            )
            self._pending[step_id] = entry
            return entry
        entry = self._pending.pop(step_id)
        entry.observation_after_summary = summarize_observation(observation_after)
        entry.state_after = task_state.serialize()
        entry.trust_snapshot = self._trust_snapshot(task_state)
        entry.checkpoint_reason = checkpoint_reason
        entry.checkpoint_kind = checkpoint_kind
        if guard_result is not None:
            entry.guard_judgement = guard_result.judgement
            entry.unknown_reason = guard_result.unknown_reason
        if debt_update is not None:
            entry.information_gain = debt_update.information_gain
            entry.verification_debt = debt_update.state.debt_score
            entry.verifier_id = next(iter(debt_update.state.attempted_verifiers), None)
        if contract is not None:
            entry.active_contract_id = contract.contract_id
            entry.contract_version = getattr(contract, "version", None)
            entry.evidence_sources_used = tuple(source.value for source in contract.sources)
        self.storage.append(entry)
        return entry
