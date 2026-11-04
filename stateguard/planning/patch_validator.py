"""Validate and atomically apply local DAG patches on plain node mappings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..environment.capabilities import EnvironmentCapabilities
from ..verification.validator import validate_task_graph
from .plan_patch import PlanPatch


class PatchValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PatchValidationResult:
    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    patched_nodes: dict[str, dict[str, Any]] | None = None


def validate_plan_patch(
    current_nodes: Mapping[str, Any],
    patch: PlanPatch,
    capabilities: EnvironmentCapabilities,
    verifier_registry=None,
    protected_node_ids: set[str] | frozenset[str] = frozenset(),
) -> PatchValidationResult:
    errors: list[str] = []
    before = _serialize_nodes(current_nodes)
    replace = set(patch.replace_nodes)
    immutable = set(protected_node_ids)
    preserved = set(patch.preserved_node_ids)

    if patch.trigger_node_id not in replace:
        errors.append("trigger node must be included in replace_nodes")
    missing_replaced = sorted(replace - set(before))
    if missing_replaced:
        errors.append(f"replace_nodes do not exist: {missing_replaced}")
    protected_replaced = sorted(replace & (immutable | preserved))
    if protected_replaced:
        errors.append(f"patch attempts to replace protected nodes: {protected_replaced}")

    new_ids = [str(node.get("node_id", "")) for node in patch.new_nodes]
    if any(not node_id for node_id in new_ids):
        errors.append("every new node must have a non-empty node_id")
    if len(new_ids) != len(set(new_ids)):
        errors.append("new node IDs must be unique")
    collisions = sorted(set(new_ids) & (set(before) - replace))
    if collisions:
        errors.append(f"new node IDs collide with retained nodes: {collisions}")
    if patch.replacement_anchor not in set(new_ids):
        errors.append("replacement_anchor must identify a new node")
    unknown_rewrites = sorted(set(patch.dependency_rewrites) - ((set(before) - replace) | set(new_ids)))
    if unknown_rewrites:
        errors.append(f"dependency rewrites target unknown nodes: {unknown_rewrites}")

    if errors:
        return PatchValidationResult(False, tuple(errors))

    candidate = _apply_unchecked(before, patch)
    original_invariant = _semantic_invariant(before[patch.trigger_node_id])
    anchor_invariant = _semantic_invariant(candidate[patch.replacement_anchor])
    if original_invariant is not None and anchor_invariant != original_invariant:
        errors.append(
            "replacement_anchor must preserve the trigger node semantic invariant")
    for node_id, node in candidate.items():
        dependencies = list(node.get("dependencies", ()))
        missing = sorted(set(dependencies) - set(candidate))
        if missing:
            errors.append(f"node {node_id} has missing dependencies: {missing}")
        if node_id in dependencies:
            errors.append(f"node {node_id} depends on itself")

    if not errors and _has_cycle(candidate):
        errors.append("patched graph contains a cycle")
    if not errors:
        unreachable = _unreachable_required_nodes(candidate)
        if unreachable:
            errors.append(f"patched graph has unreachable required nodes: {unreachable}")

    if not errors:
        new_node_values = [candidate[node_id] for node_id in new_ids]
        for node in new_node_values:
            if not isinstance(node.get("semantic_goal"), dict) \
                    or not node["semantic_goal"].get("invariant"):
                errors.append(f"new node {node['node_id']}: semantic_goal is required")
            if not isinstance(node.get("verification_intent"), dict) \
                    or not node["verification_intent"].get("target_claim"):
                errors.append(f"new node {node['node_id']}: verification_intent is required")
        contract_result = validate_task_graph(
            new_node_values, capabilities, verifier_registry
        )
        errors.extend(
            f"new node {item.node_id}: {item.reason}"
            for item in contract_result.invalid_nodes
        )

    for node_id in immutable:
        if node_id not in before:
            errors.append(f"protected node {node_id} does not exist")
        elif candidate.get(node_id) != before[node_id]:
            errors.append(f"protected node {node_id} was modified")

    for node_id in preserved:
        if node_id not in before:
            errors.append(f"preserved node {node_id} does not exist")
        elif node_id not in candidate:
            errors.append(f"preserved node {node_id} was removed")
        elif _without_dependencies(candidate[node_id]) != _without_dependencies(before[node_id]):
            errors.append(f"preserved node {node_id} changed outside dependencies")

    return PatchValidationResult(not errors, tuple(errors), candidate if not errors else None)


def apply_plan_patch(
    current_nodes: Mapping[str, Any],
    patch: PlanPatch,
    capabilities: EnvironmentCapabilities,
    verifier_registry=None,
    protected_node_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    result = validate_plan_patch(
        current_nodes,
        patch,
        capabilities,
        verifier_registry,
        protected_node_ids,
    )
    if not result.valid or result.patched_nodes is None:
        raise PatchValidationError("; ".join(result.errors))
    return deepcopy(result.patched_nodes)


def _apply_unchecked(
    before: dict[str, dict[str, Any]], patch: PlanPatch
) -> dict[str, dict[str, Any]]:
    replace = set(patch.replace_nodes)
    candidate = {
        node_id: deepcopy(node) for node_id, node in before.items() if node_id not in replace
    }
    for node in patch.new_nodes:
        value = deepcopy(node)
        value.setdefault("status", "pending")
        value.setdefault("evidence", [])
        candidate[str(node["node_id"])] = value

    for node_id, node in candidate.items():
        if node_id in patch.dependency_rewrites:
            node["dependencies"] = list(patch.dependency_rewrites[node_id])
            continue
        dependencies = list(node.get("dependencies", ()))
        rewritten: list[str] = []
        for dependency in dependencies:
            target = patch.replacement_anchor if dependency in replace else dependency
            if target not in rewritten:
                rewritten.append(target)
        node["dependencies"] = rewritten
    return candidate


def _serialize_nodes(current_nodes: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for node_id, node in current_nodes.items():
        if isinstance(node, dict):
            value = deepcopy(node)
        elif hasattr(node, "to_dict"):
            value = deepcopy(node.to_dict())
        else:
            raise TypeError(f"node {node_id!r} cannot be serialized")
        value.setdefault("node_id", node_id)
        result[str(node_id)] = value
    return result


def _without_dependencies(node: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(node)
    value.pop("dependencies", None)
    return value


def _semantic_invariant(node: dict[str, Any]) -> Any:
    goal = node.get("semantic_goal")
    return goal.get("invariant") if isinstance(goal, dict) else None


def _has_cycle(nodes: Mapping[str, dict[str, Any]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(parent) for parent in nodes[node_id].get("dependencies", ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in nodes)


def _unreachable_required_nodes(nodes: Mapping[str, dict[str, Any]]) -> list[str]:
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    roots = []
    for node_id, node in nodes.items():
        dependencies = list(node.get("dependencies", ()))
        if not dependencies:
            roots.append(node_id)
        for parent in dependencies:
            children[parent].append(node_id)
    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(children[node_id])
    return sorted(
        node_id
        for node_id, node in nodes.items()
        if node.get("required", True) and node_id not in reachable
    )
