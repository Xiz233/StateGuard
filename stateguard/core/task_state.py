"""VerifiedTaskState: node registry with legal-status-transition enforcement
and JSON round-trip (指引.txt §10)."""

from __future__ import annotations

from .schema import NodeStatus, TaskNode, Evidence


class IllegalTransitionError(Exception):
    pass


# Allowed transitions (指引.txt §10) plus the two extra ones the fault
# pipeline needs: VERIFIED -> FAILED (root discovered after the fact) and
# STALE -> FAILED (root that was already invalidated).
_ALLOWED: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.PENDING: {NodeStatus.ACTIVE},
    NodeStatus.ACTIVE: {NodeStatus.EXECUTED, NodeStatus.FAILED, NodeStatus.STALE},
    NodeStatus.EXECUTED: {NodeStatus.VERIFIED, NodeStatus.FAILED, NodeStatus.STALE},
    NodeStatus.VERIFIED: {NodeStatus.STALE, NodeStatus.FAILED},
    NodeStatus.FAILED: {NodeStatus.ACTIVE},
    NodeStatus.STALE: {NodeStatus.ACTIVE, NodeStatus.FAILED},
}


class VerifiedTaskState:
    def __init__(self, nodes: dict[str, TaskNode]):
        self.nodes: dict[str, TaskNode] = dict(nodes)

    def get(self, node_id: str) -> TaskNode:
        return self.nodes[node_id]

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.nodes

    def _transition(self, node_id: str, to: NodeStatus) -> TaskNode:
        node = self.nodes[node_id]
        if to not in _ALLOWED[node.status]:
            raise IllegalTransitionError(
                f"illegal transition {node.status.value} -> {to.value} for node {node_id}"
            )
        node.status = to
        return node

    def mark_active(self, node_id: str) -> None:
        self._transition(node_id, NodeStatus.ACTIVE)

    def mark_executed(self, node_id: str) -> None:
        self._transition(node_id, NodeStatus.EXECUTED)

    def mark_verified(self, node_id: str, evidence: Evidence | list[Evidence]) -> None:
        evs = evidence if isinstance(evidence, list) else [evidence]
        if not evs:
            raise ValueError(f"cannot mark {node_id} VERIFIED without evidence (指引 §8)")
        self._transition(node_id, NodeStatus.VERIFIED)
        self.nodes[node_id].evidence = list(evs)

    def mark_failed(self, node_id: str) -> None:
        self._transition(node_id, NodeStatus.FAILED)

    def mark_stale(self, node_ids: list[str]) -> None:
        for nid in node_ids:
            self._transition(nid, NodeStatus.STALE)

    def verified_nodes(self) -> list[str]:
        return sorted(
            (nid for nid, n in self.nodes.items()
             if n.status == NodeStatus.VERIFIED),
            key=self._topo_hint,
        )

    def incomplete_required_nodes(self) -> list[str]:
        return [
            nid for nid, n in self.nodes.items()
            if n.required and n.status != NodeStatus.VERIFIED
        ]

    def can_finish(self) -> bool:
        # FINISH rule (指引.txt §17): all required nodes VERIFIED.
        return all(
            n.status == NodeStatus.VERIFIED
            for n in self.nodes.values()
            if n.required
        )

    def _topo_hint(self, node_id: str) -> int:
        # stable order only; real topological order lives in DependencyGraph
        return sorted(self.nodes).index(node_id)

    def apply(self, updates: list[dict]) -> None:
        """Apply guard-emitted state updates; illegal sequences raise."""
        for u in updates:
            op = u["op"]
            if op == "stale":
                self.mark_stale(u["node_ids"])
                continue
            nid = u["node_id"]
            if op == "active":
                self.mark_active(nid)
            elif op == "execute":
                self.mark_executed(nid)
            elif op == "verify":
                self.mark_verified(nid, Evidence.from_dict(u["evidence"]))
            elif op == "fail":
                self.mark_failed(nid)
            else:
                raise ValueError(f"unknown update op {op!r}")

    def serialize(self) -> dict:
        return {"nodes": {nid: n.to_dict() for nid, n in self.nodes.items()}}

    @classmethod
    def deserialize(cls, data: dict) -> "VerifiedTaskState":
        state = cls({nid: TaskNode.from_dict(d) for nid, d in data["nodes"].items()})
        for node in state.nodes.values():
            if node.status == NodeStatus.VERIFIED and not node.evidence:
                raise ValueError(f"deserialized node {node.node_id} is VERIFIED without evidence")
        return state
