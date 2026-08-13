"""Deterministic validation of task specs (指引.txt §21B): unique ids,
dependencies exist, graph acyclic, required fields present, valid devices."""

from __future__ import annotations

from ..core.dependency_graph import DependencyGraph, DependencyError


class ValidationError(Exception):
    pass


def validate_spec(spec: dict, available_devices: list[str] | None = None) -> None:
    errors: list[str] = []
    nodes = spec.get("nodes", [])
    if not nodes:
        errors.append("spec has no nodes")
    if nodes and not any(n.get("required", True) for n in nodes):
        errors.append("spec has no required nodes")

    ids = [n["node_id"] for n in nodes]
    if len(set(ids)) != len(ids):
        errors.append("node ids are not unique")

    by_id = {n["node_id"]: n for n in nodes}
    for n in nodes:
        if not n.get("node_id"):
            errors.append("node without node_id")
            continue
        if not n.get("description"):
            errors.append(f"node {n.get('node_id')}: description is required")
        if not (n.get("expected_result") or n.get("expected_result_semantic")):
            errors.append(f"node {n.get('node_id')}: expected result is required")
        if n.get("dependencies") is None:
            errors.append(f"node {n['node_id']}: dependencies is required")
        for d in n.get("dependencies", []):
            if d not in by_id:
                errors.append(f"node {n['node_id']}: dependency {d!r} does not exist")
        dev = n.get("device")
        if available_devices and dev and dev not in available_devices:
            errors.append(f"node {n['node_id']}: device {dev!r} not in {available_devices}")
        if n.get("status", "pending") != "pending":
            errors.append(f"node {n['node_id']}: compiled nodes must start PENDING")
        if n.get("evidence"):
            errors.append(f"node {n['node_id']}: compiled nodes cannot carry evidence")

    if not errors:
        try:
            DependencyGraph.from_spec(nodes).validate_acyclic()
        except DependencyError as e:
            errors.append(str(e))

    if errors:
        raise ValidationError("; ".join(errors))
