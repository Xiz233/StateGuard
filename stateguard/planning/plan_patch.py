"""A bounded replacement for one problematic region of a task DAG."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlanPatch:
    trigger_node_id: str
    replace_nodes: tuple[str, ...]
    new_nodes: tuple[dict[str, Any], ...]
    dependency_rewrites: dict[str, tuple[str, ...]]
    replacement_anchor: str
    preserved_node_ids: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "replace_nodes", tuple(self.replace_nodes))
        object.__setattr__(self, "new_nodes", tuple(deepcopy(self.new_nodes)))
        object.__setattr__(
            self,
            "dependency_rewrites",
            {key: tuple(value) for key, value in self.dependency_rewrites.items()},
        )
        object.__setattr__(self, "preserved_node_ids", tuple(self.preserved_node_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_node_id": self.trigger_node_id,
            "replace_nodes": list(self.replace_nodes),
            "new_nodes": deepcopy(list(self.new_nodes)),
            "dependency_rewrites": {
                key: list(value) for key, value in self.dependency_rewrites.items()
            },
            "replacement_anchor": self.replacement_anchor,
            "preserved_node_ids": list(self.preserved_node_ids),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanPatch":
        value = _unwrap_patch(value)
        value = dict(value)
        aliases = {
            "nodes_to_replace": "replace_nodes",
            "replacement_nodes": "new_nodes",
            "preserved_nodes": "preserved_node_ids",
            "downstream_anchor": "replacement_anchor",
        }
        for source, target in aliases.items():
            if target not in value and source in value:
                value[target] = value[source]
        rewrites = value.get("dependency_rewrites", {})
        if isinstance(rewrites, list):
            normalised = {}
            for item in rewrites:
                if not isinstance(item, dict) \
                        or "node_id" not in item or "dependencies" not in item:
                    raise ValueError(
                        "each dependency rewrite needs node_id and dependencies")
                normalised[str(item["node_id"])] = tuple(item["dependencies"])
            rewrites = normalised
        if not isinstance(rewrites, dict):
            raise TypeError("dependency_rewrites must be an object or a list of rewrites")
        return cls(
            trigger_node_id=str(value["trigger_node_id"]),
            replace_nodes=tuple(value["replace_nodes"]),
            new_nodes=tuple(value["new_nodes"]),
            dependency_rewrites={
                key: tuple(dependencies)
                for key, dependencies in rewrites.items()
            },
            replacement_anchor=str(value["replacement_anchor"]),
            preserved_node_ids=tuple(value.get("preserved_node_ids", ())),
            rationale=str(value.get("rationale", "")),
        )


def _unwrap_patch(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        if not value:
            raise ValueError("empty plan patch response")
        value = value[0]
    if not isinstance(value, dict):
        raise TypeError("plan patch response must be an object")
    for key in ("plan_patch", "patch", "result"):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value
