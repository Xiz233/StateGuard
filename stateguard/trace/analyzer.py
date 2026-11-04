from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeTraceSummary:
    node_id: str
    steps_on_node: int = 0
    unknown_count: int = 0
    same_contract_unknown_count: int = 0
    contract_revision_count: int = 0
    unique_verifiers: tuple[str, ...] = field(default_factory=tuple)
    unique_evidence_sources: tuple[str, ...] = field(default_factory=tuple)
    executor_done_claims: int = 0
    no_information_gain_steps: int = 0
    last_progress_step: int | None = None
    current_debt: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def summarize_node_trace(entries, node_id: str, contract_events=(), current_debt=0):
    relevant = [entry for entry in entries if entry.active_node_id == node_id]
    contract_ids = [entry.active_contract_id for entry in relevant
                    if getattr(entry, "active_contract_id", None)]
    unknown = [entry for entry in relevant
               if getattr(entry, "guard_judgement", None) == "unknown"]
    gains = [entry for entry in relevant if getattr(entry, "information_gain", False)]
    return NodeTraceSummary(
        node_id=node_id,
        steps_on_node=len(relevant),
        unknown_count=len(unknown),
        same_contract_unknown_count=sum(
            1 for entry in unknown
            if contract_ids and entry.active_contract_id == contract_ids[-1]),
        contract_revision_count=sum(
            1 for event in contract_events
            if event.node_id == node_id and event.accepted and event.from_contract),
        unique_verifiers=tuple(sorted({entry.verifier_id for entry in relevant
                                      if getattr(entry, "verifier_id", None)})),
        unique_evidence_sources=tuple(sorted({source for entry in relevant
                                              for source in getattr(
                                                  entry, "evidence_sources_used", ())})),
        executor_done_claims=sum(
            bool(getattr(entry, "subgoal_done", False)) for entry in relevant),
        no_information_gain_steps=len(relevant) - len(gains),
        last_progress_step=gains[-1].step_id if gains else None,
        current_debt=current_debt,
    )
