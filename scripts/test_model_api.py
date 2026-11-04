from __future__ import annotations

import argparse
import json
from pathlib import Path

from stateguard.executor.parser import ActionBounds, parse_executor_output
from stateguard.guard.parser import parse_guard_output
from stateguard.models import create_model_client, load_model_config


EXECUTOR_SCHEMA = {
    "type": "object",
    "required": ["subgoal_id", "intent", "expected_effect", "action", "is_finish"],
}
GUARD_SCHEMA = {
    "type": "object",
    "required": ["judgement", "progress_updates", "fault_root", "fault_type",
                 "verification_target", "reason"],
}
FAULT_TYPES = (
    "missing_subgoal", "wrong_target", "wrong_value", "wrong_format",
    "not_persisted", "no_effect", "dependency_violation", "premature_finish",
)


def executor_smoke(client, image: str) -> dict:
    prompt = (
        "You are a frozen GUI executor. Inspect the screenshot and propose exactly one safe atomic "
        "action as JSON with subgoal_id, intent, expected_effect, action, is_finish. The action "
        "must be one of click{x,y}, type{text}, hotkey{keys}, scroll{dx,dy}, "
        "drag{x1,y1,x2,y2}, wait{}. Use subgoal_id S1 and do not emit markdown."
    )
    response = client.generate([{"role": "user", "content": prompt}], [image], EXECUTOR_SCHEMA)
    proposal = parse_executor_output(response.parsed, ActionBounds(1920, 1080))
    return {"model": response.model, "latency_seconds": response.latency_seconds,
            "usage": response.usage, "parsed": proposal.to_dict(), "passed": True}


def guard_smoke(client, manifest: str) -> dict:
    cases = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or {case.get("expected") for case in cases} != {
            "verified", "contradicted", "unknown"}:
        raise ValueError("guard case manifest must cover verified, contradicted, and unknown")
    results = []
    for case in cases:
        images = [case["before"], case["after"]]
        node_ids = list(case["task_dag"]["nodes"])
        prompt = json.dumps({
            "instruction": case["instruction"],
            "task_dag": case["task_dag"],
            "proposal": case["proposal"],
            "case_context": case.get("context", ""),
            "decision_rules": [
                "Use only visible before/after evidence and case_context.",
                "If judgement is contradicted, fault_root must be one of task_dag_node_ids and "
                "fault_type must be one of valid_fault_types.",
                "If judgement is verified or unknown, fault_root and fault_type must be null.",
                "Use wrong_value when the correct target changed to an incorrect visible value.",
                "Each progress update must contain node_id, status='verified', and visual evidence.",
            ],
            "task_dag_node_ids": node_ids,
            "valid_fault_types": FAULT_TYPES,
            "output_contract": {
                "judgement": "verified|contradicted|unknown",
                "progress_updates": "verified nodes with visual evidence only",
                "fault_root": f"one of {node_ids} when contradicted, otherwise null",
                "fault_type": "one of valid_fault_types when contradicted, otherwise null",
                "verification_target": "what evidence is needed when unknown, else null",
                "reason": "brief evidence-grounded reason",
            },
        })
        messages = [{"role": "user", "content": prompt}]
        for parse_attempt in range(2):
            response = client.generate(messages, images, GUARD_SCHEMA)
            try:
                parsed = parse_guard_output(response.parsed)
                break
            except ValueError as exc:
                if parse_attempt:
                    raise ValueError(
                        f"case {case['case_id']} invalid Guard output after correction: "
                        f"{exc}; output={response.parsed!r}"
                    ) from exc
                messages.extend([
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content": (
                        f"Invalid Guard JSON: {exc}. Correct it. For contradicted, set "
                        f"fault_root to one of {node_ids!r} and fault_type to one of "
                        f"{FAULT_TYPES!r}; otherwise set both to null. Return JSON only."
                    )},
                ])
        expected_fault = case.get("expected_fault_type")
        passed = (parsed.judgement == case["expected"] and
                  parsed.fault_type == expected_fault)
        results.append({"case_id": case["case_id"], "expected": case["expected"],
                        "expected_fault_type": expected_fault,
                        "actual": parsed.judgement, "passed": passed,
                        "model": response.model, "latency_seconds": response.latency_seconds,
                        "parsed": parsed.to_dict()})
    return {"passed": all(item["passed"] for item in results), "cases": results}


def write_report(path: str, provider: str, result: dict):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    status = "REUSE" if result.get("passed") else "REDEPLOY"
    lines = [f"# {provider} model audit", "", f"**Decision: {status}**", "",
             "```json", json.dumps(result, indent=2), "```", ""]
    target.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/models.yaml")
    parser.add_argument("--provider", choices=("executor_qwen", "stateguard_api"), required=True)
    parser.add_argument("--image", help="Required for executor_qwen")
    parser.add_argument("--cases", help="Guard before/after case manifest")
    parser.add_argument("--report")
    args = parser.parse_args()
    client = create_model_client(load_model_config(args.config)[args.provider])
    if args.provider == "executor_qwen":
        if not args.image:
            raise ValueError("--image is required for executor_qwen smoke")
        result = executor_smoke(client, args.image)
    else:
        if not args.cases:
            raise ValueError("--cases is required for stateguard_api semantic smoke")
        result = guard_smoke(client, args.cases)
    if args.report:
        write_report(args.report, args.provider, result)
    print(json.dumps(result, indent=2))
    if not result.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
