"""Deterministic DAG over task nodes (指引.txt §11). Only fault_root is a
judgement; downstream invalidation always uses graph.descendants()."""

from __future__ import annotations

import graphlib
from collections import deque

from .schema import NodeStatus, TaskNode
from .task_state import VerifiedTaskState


class DependencyError(Exception):
    pass


class DependencyGraph:
    def __init__(self, adj: dict[str, list[str]]):
        # ponytail: adjacency-as-dependencies is all we need; children/closure
        # are derived on the fly. No separate node registry.
        self._adj = {k: list(v) for k, v in adj.items()}
        for deps in self._adj.values():
            for d in deps:
                if d not in self._adj:
                    raise DependencyError(f"dependency {d!r} does not exist")
        self._children: dict[str, list[str]] = {k: [] for k in self._adj}
        for k, deps in self._adj.items():
            for d in deps:
                self._children[d].append(k)
        self._topo: list[str] | None = None

    @classmethod
    def from_state(cls, state: VerifiedTaskState) -> "DependencyGraph":
        return cls({nid: list(n.dependencies) for nid, n in state.nodes.items()})

    @classmethod
    def from_spec(cls, spec_nodes: list[dict]) -> "DependencyGraph":
        return cls({n["node_id"]: list(n.get("dependencies", [])) for n in spec_nodes})

    def nodes(self) -> list[str]:
        return list(self._adj)

    def parents(self, node: str) -> list[str]:
        if node not in self._adj:
            raise KeyError(node)
        return list(self._adj[node])

    def children(self, node: str) -> list[str]:
        if node not in self._children:
            raise KeyError(node)
        return list(self._children[node])

    def ancestors(self, node: str) -> list[str]:
        seen: set[str] = set()
        q = deque(self._adj.get(node, []))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._adj[cur])
        order = self.topological_order()
        return [n for n in order if n in seen]

    def descendants(self, node: str) -> list[str]:
        seen: set[str] = set()
        q = deque(self._children.get(node, []))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._children[cur])
        order = self.topological_order()
        return [n for n in order if n in seen]

    def topological_order(self) -> list[str]:
        if self._topo is None:
            self.validate_acyclic()
            self._topo = list(graphlib.TopologicalSorter(self._adj).static_order())
        return list(self._topo)

    def validate_acyclic(self) -> None:
        # ponytail: stdlib graphlib raises CycleError on cyclic graphs
        try:
            list(graphlib.TopologicalSorter(self._adj).static_order())
        except graphlib.CycleError as e:
            raise DependencyError(f"graph contains a cycle: {e}") from e

    def affected_set(self, root: str) -> list[str]:
        return [root] + self.descendants(root)

    def executable_frontier(self, task_state: VerifiedTaskState) -> list[str]:
        """Deterministic frontier: nodes whose dependencies are all VERIFIED
        and which are not yet VERIFIED themselves (eligible for execution or
        repair). The LLM never decides dependency satisfaction; this helper
        does."""
        return [nid for nid in self.topological_order()
                if task_state.get(nid).status != NodeStatus.VERIFIED
                and all(task_state.get(p).status == NodeStatus.VERIFIED
                        for p in self.parents(nid))]
