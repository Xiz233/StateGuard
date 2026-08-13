"""Fault case construction + ground truth (指引.txt §25/26).

A FaultCase wraps a faulted task spec (what the env+executor actually run),
the hints steering buggy agent behavior, the fixes the repair loop applies,
and the ground-truth label for offline metrics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from stateguard.core.dependency_graph import DependencyGraph
from stateguard.core.schema import FaultType
from .fault_types import INJECTABLE


@dataclass
class FaultCase:
    name: str
    task_spec: dict                       # faulted spec
    ground_truth: dict                    # §26 format
    hints: dict = field(default_factory=dict)
    fixes: dict = field(default_factory=dict)  # {"effects": {action: effect}, "params": {node: params}}
    target_node: str = ""


def inject(spec: dict, fault_type: FaultType,
           target_node: str | None = None) -> FaultCase:
    """Build a FaultCase by transforming spec for the given fault type."""
    ft = fault_type.value
    faults = spec.get("fault_targets", {})
    node = target_node or faults.get(ft)
    if node is None:
        raise ValueError(f"no {ft} fault target in task {spec['name']}")
    node_spec = next(n for n in spec["nodes"] if n["node_id"] == node)
    if ft == "not_persisted" and not node_spec.get("verify_action"):
        raise ValueError(f"not_persisted needs a persistence node, got {node}")
    if ft in ("missing_subgoal", "dependency_violation") \
            and not DependencyGraph.from_spec(spec["nodes"]).children(node):
        raise ValueError(f"{ft} target {node} must have children")

    faulted = deepcopy(spec)
    hints: dict = {}
    fixes: dict = {"effects": {}, "params": {}}
    action_name = node_spec["action"]

    if ft == "wrong_target":
        # action hits the wrong location: replace the effect values
        effect = faulted["actions"][action_name]["effect"]
        fixes["effects"][action_name] = deepcopy(effect)
        faulted["actions"][action_name]["effect"] = {k: "WRONG_TARGET" for k in effect}
    elif ft == "wrong_value":
        fixes["params"][node] = deepcopy(node_spec.get("action_params", {}))
        fnode = next(n for n in faulted["nodes"] if n["node_id"] == node)
        fnode["action_params"] = {p: {"lit": "WRONG_VALUE"}
                                  for p in node_spec.get("action_params", {})}
    elif ft == "missing_subgoal":
        hints = {"skip": [node]}
    elif ft == "no_effect":
        effect = faulted["actions"][action_name]["effect"]
        fixes["effects"][action_name] = deepcopy(effect)
        faulted["actions"][action_name]["effect"] = {}
    elif ft == "not_persisted":
        effect = faulted["actions"][action_name]["effect"]
        fixes["effects"][action_name] = deepcopy(effect)
        faulted["actions"][action_name]["effect"] = {
            f"__temp__.{k}": v for k, v in effect.items()
        }
    elif ft == "premature_finish":
        hints = {"premature_finish": True}
    elif ft == "dependency_violation":
        hints = {"ignore_unknown": [node]}
    else:
        raise ValueError(f"unsupported fault type {ft}")

    gt = ground_truth(spec, node, ft)
    return FaultCase(name=f"{spec['name']}__{ft}", task_spec=faulted,
                     ground_truth=gt, hints=hints, fixes=fixes, target_node=node)


def ground_truth(spec: dict, root: str, ftype: FaultType) -> dict:
    """§26 format: affected = root + descendants; preservable = other
    required nodes."""
    graph = DependencyGraph.from_spec(spec["nodes"])
    affected = graph.affected_set(root)
    required = [n["node_id"] for n in spec["nodes"] if n.get("required", True)]
    return {
        "fault_type": ftype.value if isinstance(ftype, FaultType) else ftype,
        "fault_root": root,
        "affected_nodes": affected,
        "preservable_nodes": sorted(set(required) - set(affected)),
    }


def make_cases(tasks: list[dict], fault_types: list[FaultType] | None = None) -> list[FaultCase]:
    """All injectable cases for the given tasks (skips inapplicable ones)."""
    ft_list = fault_types or INJECTABLE
    cases = []
    for spec in tasks:
        for ft in ft_list:
            try:
                cases.append(inject(spec, ft))
            except ValueError:
                continue
    return cases
