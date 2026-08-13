"""TaskCompiler (指引.txt §21).

A. compile_from_spec: manual synthetic compiler (unit-test / demo path).
B. compile_from_instruction: LLM compiler interface; Phase I uses a
   deterministic mock (fixed output schema only).
"""

from __future__ import annotations

from ..core.schema import TaskNode, NodeStatus
from ..core.task_state import VerifiedTaskState
from .validator import validate_spec, ValidationError


def compile_from_spec(spec: dict, available_devices: list[str] | None = None) -> VerifiedTaskState:
    validate_spec(spec, available_devices)
    nodes = {}
    for n in spec["nodes"]:
        node = TaskNode(
            node_id=n["node_id"],
            description=n["description"],
            device=n.get("device"),
            app=n.get("app"),
            dependencies=list(n.get("dependencies", [])),
            expected_result=n["expected_result"],
            expected_effect=dict(n.get("expected_effect", {})),
            verify_action=n.get("verify_action"),
            status=NodeStatus.PENDING,
            required=n.get("required", True),
        )
        nodes[node.node_id] = node
    return VerifiedTaskState(nodes)


def compile_from_instruction(instruction: str,
                             available_devices: list[str] | None = None) -> VerifiedTaskState:
    """Mock LLM compiler: fixed schema, deterministic chain from an
    instruction of lines '<id> <description>'. Swap for a real LLM later
    (prompts in stateguard/guard/prompts.py)."""
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
