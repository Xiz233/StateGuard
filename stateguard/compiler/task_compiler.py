"""TaskCompiler (指引.txt §21).

A. compile_from_spec: manual synthetic compiler (unit-test / demo path).
B. compile_from_instruction: LLM compiler interface; Phase I uses a
   deterministic mock (fixed output schema only).
"""

from __future__ import annotations

from ..core.schema import (
    NodeStatus, SemanticGoal, TaskNode, VerificationIntent,
)
from ..core.task_state import VerifiedTaskState
from ..verification.contracts import AdaptiveEvidenceContract, EvidenceContract
from .validator import validate_spec, ValidationError


def compile_from_spec(spec: dict, available_devices: list[str] | None = None) -> VerifiedTaskState:
    validate_spec(spec, available_devices)
    nodes = {}
    for n in spec["nodes"]:
        contract = n.get("evidence_contract")
        if isinstance(contract, dict):
            contract = (AdaptiveEvidenceContract.from_dict(contract)
                        if "version" in contract else EvidenceContract.from_dict(contract))
        if contract is None:
            contract = EvidenceContract.from_legacy(
                node_id=n["node_id"],
                evidence_mode=n.get("evidence_mode", "visual"),
                success_condition=n.get(
                    "expected_result_semantic", n.get("expected_result", "")
                ),
                structured_predicate=n.get("structured_predicate"),
                expected_effect=n.get("expected_effect"),
                verify_action=n.get("verify_action"),
            )
        node = TaskNode(
            node_id=n["node_id"],
            description=n["description"],
            device=n.get("device"),
            app=n.get("app"),
            dependencies=list(n.get("dependencies", [])),
            expected_result=n.get("expected_result", n.get("expected_result_semantic", "")),
            expected_effect=dict(n.get("expected_effect", {})),
            verify_action=n.get("verify_action"),
            status=NodeStatus.PENDING,
            required=n.get("required", True),
            expected_result_semantic=n.get("expected_result_semantic"),
            structured_predicate=n.get("structured_predicate"),
            evidence_mode=n.get("evidence_mode", "visual"),
            evidence_contract=contract,
            semantic_goal=(SemanticGoal.from_dict(n["semantic_goal"])
                           if isinstance(n.get("semantic_goal"), dict) else None),
            verification_intent=(VerificationIntent.from_dict(n["verification_intent"])
                                 if isinstance(n.get("verification_intent"), dict) else None),
        )
        nodes[node.node_id] = node
    return VerifiedTaskState(nodes)


def compile_from_instruction(instruction: str, available_devices: list[str] | None = None,
                             model_client=None) -> VerifiedTaskState:
    """Compile through ModelClient; retain the Phase-I mock when none is supplied."""
    if model_client:
        from ..models.client import parse_json
        prompt = ("Return JSON only with nodes containing node_id, description, "
                  "dependencies, expected_result_semantic, evidence_mode, required. "
                  "Every node must be an externally verifiable environment state; "
                  "keep private reasoning, reading, identification, and inference out "
                  "of the DAG.\n"
                  f"Devices: {available_devices or []}\nInstruction: {instruction}")
        response = model_client.generate([{"role": "user", "content": prompt}])
        spec = response.parsed or parse_json(response.text)
        for node in spec.get("nodes", []):
            node.setdefault("expected_result", node.get("expected_result_semantic", ""))
    else:
        spec = mock_llm_compile(instruction)
    return compile_from_spec(spec, available_devices)


def mock_llm_compile(instruction: str) -> dict:
    # ponytail: 6-line mock; enough to freeze the output schema end-to-end
    nodes = []
    prev = None
    for raw in instruction.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        nid, desc = parts[0], (parts[1] if len(parts) > 1 else "do the thing")
        deps = [prev] if prev else []
        nodes.append({"node_id": nid, "description": desc, "dependencies": deps,
                      "expected_result": f"{nid} completed"})
        prev = nid
    if not nodes:
        raise ValidationError("instruction produced no nodes")
    return {"nodes": nodes}
