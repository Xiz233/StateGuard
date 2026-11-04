from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from stateguard.core.dependency_graph import DependencyGraph


FAULT_TYPES = ("wrong_target", "wrong_value", "no_effect", "earlier_state_corruption")


def load_graph(path: str | Path) -> tuple[dict, DependencyGraph]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return raw, DependencyGraph.from_spec(raw.get("nodes", []))


def has_placeholder(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return "REVIEW_REQUIRED" in value
    if isinstance(value, dict):
        return any(has_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(has_placeholder(item) for item in value)
    return False


def validate_fault(spec: dict, graph: DependencyGraph, require_approved: bool = True):
    required = {"fault_id", "type", "root_node", "inject", "exposure",
                "expected_affected", "expected_preserved", "manual_review"}
    missing = required - spec.keys()
    if missing:
        raise ValueError(f"fault {spec.get('fault_id')}: missing {sorted(missing)}")
    if spec["type"] not in FAULT_TYPES:
        raise ValueError(f"fault {spec['fault_id']}: unsupported type {spec['type']!r}")
    root = spec["root_node"]
    if root not in graph.nodes():
        raise ValueError(f"fault {spec['fault_id']}: root {root!r} not in graph")
    trigger = spec["inject"].get("trigger", {})
    if trigger.get("subgoal_id") != root:
        raise ValueError(f"fault {spec['fault_id']}: injection trigger must equal root")
    mutation = spec["inject"].get("mutation", {})
    if require_approved and not trigger.get("action_type"):
        raise ValueError(f"fault {spec['fault_id']}: approved fault needs action_type trigger")
    if spec["type"] == "wrong_target" and require_approved:
        if trigger["action_type"] not in {"click", "drag"}:
            raise ValueError(f"fault {spec['fault_id']}: wrong_target needs click or drag trigger")
        if not ({"coordinate_offset", "action_override"} & mutation.keys()):
            raise ValueError(f"fault {spec['fault_id']}: wrong_target needs target mutation")
    if spec["type"] == "wrong_value" and require_approved:
        if trigger["action_type"] != "type" or not mutation.get("replace_text"):
            raise ValueError(f"fault {spec['fault_id']}: wrong_value needs type/replace_text")
    expected_affected = [root] + graph.descendants(root)
    if spec["expected_affected"] != expected_affected:
        raise ValueError(f"fault {spec['fault_id']}: expected_affected is not DAG closure")
    expected_preserved = [node for node in graph.topological_order()
                          if node not in expected_affected]
    if spec["expected_preserved"] != expected_preserved:
        raise ValueError(f"fault {spec['fault_id']}: expected_preserved is inconsistent")
    if spec["type"] == "earlier_state_corruption":
        if len(graph.nodes()) < 4:
            raise ValueError(f"fault {spec['fault_id']}: earlier corruption needs >=4 nodes")
        exposure = spec["exposure"]
        exposed_at = exposure.get("trigger", {}).get("subgoal_id")
        if exposure.get("mode") not in {"delayed", "latent"} or exposed_at not in graph.descendants(root):
            raise ValueError(f"fault {spec['fault_id']}: earlier corruption needs downstream exposure")
    review = spec["manual_review"]
    if require_approved and not all(review.get(key) for key in
                                    ("approved", "approved_by", "approved_at")):
        raise ValueError(f"fault {spec['fault_id']}: manual review is not approved")
    if require_approved and has_placeholder(spec["inject"].get("mutation")):
        raise ValueError(f"fault {spec['fault_id']}: mutation still contains placeholders")


def load_fault_manifest(path: str | Path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = raw.get("faults", [])
    faults = []
    for entry in entries:
        spec = yaml.safe_load(Path(entry["spec_file"]).read_text(encoding="utf-8"))
        faults.append({"task_id": entry["task_id"], "spec_file": entry["spec_file"],
                       "spec": spec})
    return faults


def validate_distribution(faults: list[dict]):
    if len(faults) != 24:
        raise ValueError(f"fault manifest must contain 24 faults, got {len(faults)}")
    counts = Counter(item["spec"]["type"] for item in faults)
    expected = {fault_type: 6 for fault_type in FAULT_TYPES}
    if dict(counts) != expected:
        raise ValueError(f"fault distribution must be {expected}, got {dict(counts)}")
    per_task = Counter(item["task_id"] for item in faults)
    if set(per_task.values()) != {2} or len(per_task) != 12:
        raise ValueError("each of exactly 12 tasks must have exactly two faults")
