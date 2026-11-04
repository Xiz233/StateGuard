"""Versioned adaptive contracts, kept separate from task-state transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import AdaptiveEvidenceContract, ContractStatus


@dataclass(frozen=True)
class ContractRevisionEvent:
    node_id: str
    from_contract: str | None
    to_contract: str | None
    trigger: str
    previous_failure_reason: str | None
    semantic_preserved: bool
    evidence_sources_changed: bool
    verifier_changed: bool
    step: int
    accepted: bool = True
    rejection_reason: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class ContractStore:
    def __init__(self):
        self._contracts: dict[str, list[AdaptiveEvidenceContract]] = {}
        self.events: list[ContractRevisionEvent] = []

    def active(self, node_id: str) -> AdaptiveEvidenceContract | None:
        return next((item for item in reversed(self._contracts.get(node_id, ()))
                     if item.status == ContractStatus.ACTIVE), None)

    def history(self, node_id: str) -> tuple[AdaptiveEvidenceContract, ...]:
        return tuple(self._contracts.get(node_id, ()))

    def attach(self, contract: AdaptiveEvidenceContract, trigger: str, step: int,
               previous_failure_reason: str | None = None) -> ContractRevisionEvent:
        previous = self.active(contract.node_id)
        expected_version = (previous.version + 1) if previous else 1
        if contract.version != expected_version:
            raise ValueError(
                f"contract {contract.contract_id} version {contract.version} "
                f"does not follow {expected_version - 1}")
        if previous:
            values = self._contracts[contract.node_id]
            values[-1] = replace(previous, status=ContractStatus.SUPERSEDED)
        self._contracts.setdefault(contract.node_id, []).append(contract)
        event = ContractRevisionEvent(
            node_id=contract.node_id,
            from_contract=previous.contract_id if previous else None,
            to_contract=contract.contract_id,
            trigger=trigger,
            previous_failure_reason=previous_failure_reason,
            semantic_preserved=True,
            evidence_sources_changed=bool(previous and previous.sources != contract.sources),
            verifier_changed=bool(previous and
                                  previous.preferred_verifier != contract.preferred_verifier),
            step=step,
        )
        self.events.append(event)
        return event

    def reject(self, node_id: str, trigger: str, step: int, reason: str,
               candidate_id: str | None = None) -> ContractRevisionEvent:
        previous = self.active(node_id)
        event = ContractRevisionEvent(
            node_id=node_id,
            from_contract=previous.contract_id if previous else None,
            to_contract=candidate_id,
            trigger=trigger,
            previous_failure_reason=None,
            semantic_preserved=False,
            evidence_sources_changed=False,
            verifier_changed=False,
            step=step,
            accepted=False,
            rejection_reason=reason,
        )
        self.events.append(event)
        return event

    def mark_ungroundable(self, node_id: str) -> None:
        active = self.active(node_id)
        if active:
            self._contracts[node_id][-1] = replace(
                active, status=ContractStatus.UNGROUNDABLE)

    def retire_nodes(self, node_ids) -> None:
        for node_id in node_ids:
            self.mark_ungroundable(node_id)
