"""Provider-neutral local replanning interface and bounded request context."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Protocol

from .plan_patch import PlanPatch
from ..training_logging import record_parse


@dataclass(frozen=True)
class LocalReplanRequest:
    task_goal: str
    problem_node: dict[str, Any]
    ancestor_boundary: tuple[dict[str, Any], ...]
    descendant_boundary: tuple[dict[str, Any], ...]
    current_observation_summary: dict[str, Any]
    environment_capabilities: dict[str, Any]
    verification_debt_summary: dict[str, Any]
    attempted_strategies: tuple[str, ...] = field(default_factory=tuple)
    trace_summary: dict[str, Any] = field(default_factory=dict)
    protected_verified_nodes: tuple[str, ...] = field(default_factory=tuple)


class PlanPatchProvider(Protocol):
    def propose_patch(self, request: LocalReplanRequest) -> PlanPatch: ...


class RuntimeReplanner:
    def __init__(self, provider: PlanPatchProvider) -> None:
        self.provider = provider

    def replan(self, request: LocalReplanRequest) -> PlanPatch:
        return self.provider.propose_patch(request)


class MLLMPlanPatchProvider:
    def __init__(self, model_client, max_attempts: int = 2):
        self.model_client = model_client
        self.max_attempts = max(1, int(max_attempts))
        self.calls = self.tokens = 0
        self.latency = 0.0
        self.fallback_count = 0

    def propose_patch(self, request: LocalReplanRequest) -> PlanPatch:
        prompt = json.dumps({
            "request": request.__dict__,
            "instruction": (
                "Replace the smallest unverifiable semantic DAG region. Do not restart "
                "the task, modify protected verified nodes, encode GUI actions as nodes, "
                "or weaken the task invariant. Every new node must be externally verifiable "
                "and include semantic_goal, verification_intent, and evidence_contract. "
                "preserved_node_ids means retained nodes whose semantics and fields stay "
                "unchanged; their dependencies may be reconnected to replacement_anchor. "
                "Only protected_verified_nodes are byte-for-byte immutable. "
                "Return PlanPatch JSON with trigger_node_id, replace_nodes, new_nodes, "
                "dependency_rewrites, replacement_anchor, preserved_node_ids, rationale."),
        }, default=str)
        messages = [{"role": "user", "content": prompt}]
        error = None
        for _ in range(self.max_attempts):
            response = self.model_client.generate(
                messages, response_schema=_plan_patch_schema())
            self.calls += 1
            self.latency += getattr(response, "latency_seconds", 0.0)
            self.tokens += sum((response.usage or {}).get(key, 0)
                               for key in ("prompt_tokens", "completion_tokens"))
            try:
                value = _normalise_patch_response(response.parsed or {}, request)
                patch = PlanPatch.from_dict(value)
                record_parse(self.model_client, "completed", patch.to_dict())
                return patch
            except (KeyError, TypeError, ValueError) as exc:
                record_parse(self.model_client, "failed", response.parsed, exc)
                error = exc
                messages.extend([
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content": f"Invalid PlanPatch: {exc}. Return JSON only."},
                ])
        self.fallback_count += 1
        patch = _deterministic_retry_patch(request, error)
        record_parse(self.model_client, "fallback", patch.to_dict(), error)
        return patch


def _plan_patch_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "trigger_node_id", "replace_nodes", "new_nodes",
            "dependency_rewrites", "replacement_anchor",
        ],
        "properties": {
            "trigger_node_id": {"type": "string"},
            "replace_nodes": {"type": "array", "items": {"type": "string"}},
            "new_nodes": {"type": "array", "items": {"type": "object"}},
            "dependency_rewrites": {
                "type": "object",
                "additionalProperties": {
                    "type": "array", "items": {"type": "string"}},
            },
            "replacement_anchor": {"type": "string"},
            "preserved_node_ids": {
                "type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def _normalise_patch_response(value: Any, request: LocalReplanRequest) -> dict[str, Any]:
    """Repair model syntax while binding immutable semantics locally."""
    if isinstance(value, list):
        value = value[0] if value else {}
    if not isinstance(value, dict):
        raise TypeError("plan patch response must be an object")
    for key in ("plan_patch", "patch", "result"):
        if isinstance(value.get(key), dict):
            value = value[key]
            break
    value = deepcopy(value)
    problem = request.problem_node
    trigger_id = str(problem.get("node_id", ""))
    if not trigger_id:
        raise ValueError("problem node has no node_id")
    value["trigger_node_id"] = trigger_id
    value["replace_nodes"] = [trigger_id]
    value.setdefault("dependency_rewrites", {})
    allowed_preserved = {
        str(node.get("node_id"))
        for node in (*request.ancestor_boundary, *request.descendant_boundary)
        if node.get("node_id")
    } | set(request.protected_verified_nodes)
    value["preserved_node_ids"] = [
        str(node_id) for node_id in value.get("preserved_node_ids", ())
        if str(node_id) in allowed_preserved and str(node_id) != trigger_id
    ]

    new_nodes = value.get("new_nodes", value.get("replacement_nodes"))
    if not isinstance(new_nodes, list) or not new_nodes:
        raise ValueError("new_nodes must contain at least one replacement node")
    if any(not isinstance(node, dict) for node in new_nodes):
        raise ValueError("every replacement node must be an object")
    value["new_nodes"] = [_normalise_new_node(node, request) for node in new_nodes]
    anchor = value.get("replacement_anchor", value.get("downstream_anchor"))
    ids = {str(node.get("node_id", "")) for node in value["new_nodes"]}
    if anchor not in ids:
        anchor = _infer_replacement_anchor(value["new_nodes"])
    value["replacement_anchor"] = anchor

    anchor_node = next(node for node in value["new_nodes"]
                       if str(node.get("node_id")) == anchor)
    _bind_anchor_semantics(
        anchor_node, problem, request.environment_capabilities)
    return value


def _normalise_new_node(node: dict[str, Any], request: LocalReplanRequest) -> dict[str, Any]:
    node = deepcopy(node)
    node_id = str(node.get("node_id", "")).strip()
    if not node_id:
        raise ValueError("every replacement node needs node_id")
    node["node_id"] = node_id
    node.setdefault("description", str(node.get("expected_result_semantic") or node_id))
    node["status"] = "pending"
    node["evidence"] = []
    node["dependencies"] = list(node.get("dependencies") or ())
    invariant = _node_invariant(node)
    if invariant is None:
        invariant = str(node.get("expected_result_semantic")
                        or node.get("expected_result") or node.get("description") or "").strip()
        if not invariant:
            raise ValueError(f"replacement node {node_id} has no semantic invariant")
        node["semantic_goal"] = {
            "description": invariant, "invariant": invariant, "required": True,
            "role": None,
        }
    else:
        goal = dict(node["semantic_goal"])
        goal.setdefault("description", str(invariant))
        goal.setdefault("required", bool(node.get("required", True)))
        goal.setdefault("role", None)
        node["semantic_goal"] = goal
    intent = node.get("verification_intent")
    if not isinstance(intent, dict):
        node["verification_intent"] = {
            "target_claim": str(invariant),
            "preferred_evidence_types": ["visual"],
            "persistence_required": False,
            "strength": "normal",
        }
    else:
        intent = dict(intent)
        intent.setdefault("target_claim", str(invariant))
        intent.setdefault("preferred_evidence_types", ["visual"])
        intent.setdefault("persistence_required", False)
        intent.setdefault("strength", "normal")
        node["verification_intent"] = intent
    node.setdefault("expected_result_semantic", str(invariant))
    node.setdefault("required", True)
    node["evidence_contract"] = _normalise_contract(
        node_id, invariant, node.get("evidence_contract"),
        request.environment_capabilities)
    allowed_fields = {
        "node_id", "description", "device", "app", "dependencies",
        "expected_result", "expected_effect", "verify_action", "status",
        "evidence", "required", "expected_result_semantic",
        "structured_predicate", "evidence_mode", "evidence_contract",
        "semantic_goal", "verification_intent", "active_contract_id",
        "trust_score", "suspicion_reason", "suspicious_since_step",
    }
    return {key: value for key, value in node.items() if key in allowed_fields}


def _bind_anchor_semantics(anchor: dict[str, Any], problem: dict[str, Any],
                           capabilities: dict[str, Any]) -> None:
    goal = deepcopy(problem.get("semantic_goal"))
    invariant = _node_invariant(problem)
    if invariant is None or not isinstance(goal, dict):
        invariant = (problem.get("expected_result_semantic")
                     or problem.get("expected_result") or problem.get("description"))
        goal = {"description": str(invariant), "invariant": invariant,
                "required": bool(problem.get("required", True)), "role": None}
    anchor["semantic_goal"] = goal
    anchor["expected_result_semantic"] = problem.get(
        "expected_result_semantic", goal.get("description", str(invariant)))
    intent = deepcopy(problem.get("verification_intent"))
    if not isinstance(intent, dict):
        intent = {"target_claim": str(invariant),
                  "preferred_evidence_types": ["visual"],
                  "persistence_required": False, "strength": "normal"}
    anchor["verification_intent"] = intent
    anchor["evidence_contract"] = _normalise_contract(
        anchor["node_id"], invariant, anchor.get("evidence_contract"), capabilities)


def _normalise_contract(node_id: str, invariant: Any, contract: Any,
                        capabilities: dict[str, Any]) -> dict[str, Any]:
    contract = deepcopy(contract) if isinstance(contract, dict) else {}
    available = tuple(capabilities.get("available_sources", ()))
    proposed_sources = contract.get("sources") or ()
    if isinstance(proposed_sources, str):
        proposed_sources = (proposed_sources,)
    sources = [str(source) for source in proposed_sources
               if str(source) in available]
    if not sources:
        sources = (["screenshot"] if "screenshot" in available else list(available[:1]))
    if not sources:
        sources = ["screenshot"]
    source = sources[0]
    evidence_type = {
        "screenshot": "visual",
        "external_tool": "persistence",
    }.get(source, "structured")
    verifier = contract.get("verifier_id")
    supported = set(capabilities.get("supported_verifiers", ()))
    if verifier not in supported:
        verifier = None
    result = {
        "contract_id": str(contract.get("contract_id") or f"replan:{node_id}"),
        "evidence_type": evidence_type,
        "sources": [source],
        "verifier_id": verifier,
        "predicate": contract.get("predicate"),
        "verify_action": contract.get("verify_action"),
        "observable_fields": list(contract.get("observable_fields") or ()),
        "success_condition": deepcopy(invariant),
        "contradiction_condition": contract.get("contradiction_condition"),
        "allow_mllm_fallback": source == "screenshot",
    }
    if evidence_type == "structured" and result["predicate"] is None and verifier is None:
        if "screenshot" in available:
            result["evidence_type"] = "visual"
            result["sources"] = ["screenshot"]
            result["allow_mllm_fallback"] = True
    return result


def _infer_replacement_anchor(nodes: list[dict[str, Any]]) -> str:
    depended_on = {
        str(dependency)
        for node in nodes for dependency in (node.get("dependencies") or ())
    }
    sinks = [str(node["node_id"]) for node in nodes
             if str(node["node_id"]) not in depended_on]
    if len(sinks) != 1:
        raise ValueError("replacement_anchor is missing or ambiguous")
    return sinks[0]


def _node_invariant(node: dict[str, Any]) -> Any:
    goal = node.get("semantic_goal")
    return goal.get("invariant") if isinstance(goal, dict) else None


def _deterministic_retry_patch(request: LocalReplanRequest, error) -> PlanPatch:
    problem = request.problem_node
    trigger_id = str(problem.get("node_id", "")).strip()
    if not trigger_id:
        raise ValueError(f"plan patch generation failed: {error}")
    fingerprint = hashlib.sha256(json.dumps({
        "trigger": trigger_id,
        "attempted": request.attempted_strategies,
        "debt": request.verification_debt_summary,
    }, sort_keys=True, default=str).encode()).hexdigest()[:8]
    safe_trigger = re.sub(r"[^A-Za-z0-9_-]+", "_", trigger_id)
    retry_id = f"{safe_trigger}__retry_{fingerprint}"
    node = deepcopy(problem)
    node["node_id"] = retry_id
    node["description"] = (
        f"Retry the same required outcome through a different observable route: "
        f"{problem.get('description', trigger_id)}")
    node["dependencies"] = list(problem.get("dependencies") or ())
    node = _normalise_new_node(node, request)
    _bind_anchor_semantics(node, problem, request.environment_capabilities)
    preserved = []
    for boundary in (*request.ancestor_boundary, *request.descendant_boundary):
        node_id = boundary.get("node_id")
        if node_id and node_id != trigger_id and node_id not in preserved:
            preserved.append(str(node_id))
    for node_id in request.protected_verified_nodes:
        if node_id != trigger_id and node_id not in preserved:
            preserved.append(str(node_id))
    return PlanPatch(
        trigger_node_id=trigger_id,
        replace_nodes=(trigger_id,),
        new_nodes=(node,),
        dependency_rewrites={},
        replacement_anchor=retry_id,
        preserved_node_ids=tuple(preserved),
        rationale=(
            "Deterministic semantic-preserving retry after model patch generation "
            f"failed: {error}"),
    )
