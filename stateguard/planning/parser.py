"""Deterministic Auto-DAG parser + validator (planning/phase-2).

No LLM judgement happens here: every check is a Python decision, and the
validator rejects hidden runtime fields (evaluator/gold/fault leakage) by
allowing only the TaskNode fields the runtime understands.
"""

from __future__ import annotations

import json

from ..core.dependency_graph import DependencyError, DependencyGraph

VALID_EVIDENCE_MODES = {"visual", "structured", "persistence", "hybrid"}
ALLOWED_NODE_FIELDS = {
    "node_id", "description", "dependencies", "expected_result_semantic",
    "evidence_mode", "required",
    "semantic_goal", "verification_intent",
}
MIN_NODES = 2
MAX_NODES = 8


class AutoDAGError(Exception):
    pass


def parse_auto_dag(raw) -> list[dict]:
    """Extract a validated node list from a raw model response.

    Raises AutoDAGError on any structural violation.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AutoDAGError(f"raw response is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        raise AutoDAGError("auto-DAG output must be a JSON object with a 'nodes' list")
    nodes = raw["nodes"]
    if not (MIN_NODES <= len(nodes) <= MAX_NODES):
        raise AutoDAGError(
            f"auto-DAG must have {MIN_NODES}-{MAX_NODES} nodes, got {len(nodes)}")
    parsed: list[dict] = []
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise AutoDAGError(f"node {i} is not an object")
        unknown = set(node) - ALLOWED_NODE_FIELDS
        if unknown:
            raise AutoDAGError(f"node {i} has disallowed fields {sorted(unknown)}")
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise AutoDAGError(f"node {i} needs a non-empty node_id")
        description = node.get("description")
        if not isinstance(description, str) or not description.strip():
            raise AutoDAGError(f"node {node_id} needs a non-empty description")
        deps = node.get("dependencies", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise AutoDAGError(f"node {node_id} dependencies must be a list of node ids")
        mode = node.get("evidence_mode", "visual")
        if mode not in VALID_EVIDENCE_MODES:
            raise AutoDAGError(f"node {node_id} has invalid evidence_mode {mode!r}")
        if not isinstance(node.get("required", True), bool):
            raise AutoDAGError(f"node {node_id} 'required' must be a bool")
        semantic_goal = node.get("semantic_goal") or {
            "description": node.get("expected_result_semantic") or description.strip(),
            "invariant": node.get("expected_result_semantic") or description.strip(),
            "required": node.get("required", True),
        }
        intent = node.get("verification_intent") or {
            "target_claim": semantic_goal["description"],
            "preferred_evidence_types": [mode],
            "persistence_required": mode == "persistence",
            "strength": "strong" if mode == "persistence" else "normal",
        }
        if not isinstance(semantic_goal, dict) or not semantic_goal.get("invariant"):
            raise AutoDAGError(f"node {node_id} needs a semantic_goal invariant")
        if not isinstance(intent, dict) or not intent.get("target_claim"):
            raise AutoDAGError(f"node {node_id} needs a verification_intent")
        parsed.append({
            "node_id": node_id.strip(),
            "description": description.strip(),
            "dependencies": list(deps),
            "expected_result_semantic": (node.get("expected_result_semantic")
                                         or description.strip()),
            "evidence_mode": mode,
            "required": node.get("required", True),
            "semantic_goal": semantic_goal,
            "verification_intent": intent,
        })
    return parsed


def validate_auto_dag(nodes: list[dict]) -> dict:
    """Deterministic DAG validation. Returns a report dict or raises
    AutoDAGError. All checks are pure Python: unique ids, existing
    dependencies, acyclicity, >=1 root, all required nodes reachable."""
    ids = [n["node_id"] for n in nodes]
    if len(ids) != len(set(ids)):
        raise AutoDAGError("node ids must be unique")
    try:
        graph = DependencyGraph.from_spec(nodes)  # raises on missing dependencies
        graph.validate_acyclic()                  # raises on cycles
    except DependencyError as exc:
        raise AutoDAGError(str(exc)) from exc
    roots = [nid for nid in ids if not graph.parents(nid)]
    if not roots:
        raise AutoDAGError("auto-DAG has no root node")
    reachable = set(roots)
    for r in roots:
        reachable.update(graph.descendants(r))
    missing = [nid for n, nid in zip(nodes, ids)
               if n["required"] and nid not in reachable]
    if missing:
        raise AutoDAGError(f"required nodes unreachable: {missing}")
    return {
        "valid": True,
        "node_count": len(ids),
        "edge_count": sum(len(n["dependencies"]) for n in nodes),
        "roots": sorted(roots),
    }
