"""Deterministic, evidence-backed classification of natural GUI failures."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


FAILURE_CATEGORIES = (
    "click_wrong_location",
    "typing_wrong_content",
    "missing_enter_or_incomplete_action",
    "action_no_observable_effect",
    "repeated_action",
    "excessive_wait",
    "wrong_application_or_focus",
    "wrong_subgoal_or_frontier",
    "premature_finish",
    "stuck_on_subgoal",
    "executor_assumed_success",
    "guard_unknown_without_next_evidence",
    "repeated_evidence_source",
    "no_information_gain",
    "contract_revision_without_verifier_change",
    "semantic_goal_not_observable",
    "repair_too_late_or_failed",
    "replan_operationally_ineffective",
    "step_budget_exhausted",
    "environment_or_framework_failure",
    "unknown_or_ambiguous",
)


def _json_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _actions(episode_dir: Path) -> list[tuple[int, dict]]:
    rows = _json_lines(episode_dir / "executor_events.jsonl")
    return [(int(row.get("step", 0)), (row.get("proposal") or {}).get("action") or {})
            for row in rows]


def _longest_run(values) -> int:
    longest = current = 0
    previous = object()
    for value in values:
        if value == previous:
            current += 1
        else:
            current = 1
            previous = value
        longest = max(longest, current)
    return longest


def analyze_episode(episode_dir: str | Path) -> dict:
    """Return candidate failure labels without inventing injected ground truth."""
    directory = Path(episode_dir)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    executor = _json_lines(directory / "executor_events.jsonl")
    guards = _json_lines(directory / "guard_events.jsonl")
    contracts = _json_lines(directory / "contract_events.jsonl")
    patches = _json_lines(directory / "plan_patch_events.jsonl")
    trajectory = _json_lines(directory / "trajectory.jsonl")
    labels: list[str] = []
    evidence: dict[str, list[str]] = {}

    def add(label, detail):
        if label not in labels:
            labels.append(label)
        evidence.setdefault(label, []).append(str(detail))

    actions = [(int(row.get("step", 0)), (row.get("proposal") or {}).get("action") or {})
               for row in executor]
    kinds = [action.get("type") for _, action in actions]
    longest_wait = max(
        (_longest_run(group) for group in _runs_of(kinds, "wait")), default=0)
    if longest_wait >= 3:
        add("excessive_wait", f"longest consecutive wait run={longest_wait}")
    serialized_actions = [json.dumps(action, sort_keys=True) for _, action in actions]
    if _longest_run(serialized_actions) >= 3:
        add("repeated_action", f"longest identical-action run={_longest_run(serialized_actions)}")

    command_markers = ("python", "libreoffice", "ls ", "find ", "cat ", "head ",
                       "paste ", "sed ", "awk ", "wc ", "curl ", "wget ")
    for index, (step, action) in enumerate(actions[:-1]):
        text = str(action.get("text", "")).strip().lower()
        next_action = actions[index + 1][1]
        keys = [str(key).lower() for key in next_action.get("keys", ())]
        if (action.get("type") == "type" and any(marker in text for marker in command_markers)
                and not (next_action.get("type") == "hotkey" and "enter" in keys)):
            add("missing_enter_or_incomplete_action",
                f"step {step} typed a likely command without an immediate Enter action")
            break

    finish_claims = [row.get("step") for row in executor
                     if (row.get("proposal") or {}).get("is_finish")]
    if result.get("premature_finish_count", 0) or finish_claims and not result.get("success"):
        add("premature_finish", f"finish claims={finish_claims}")

    if result.get("frontier_violation_count", 0) or "frontier" in str(result.get("error", "")):
        add("wrong_subgoal_or_frontier", result.get("error") or "frontier violation recorded")
    if result.get("status") in {
        "environment_failed", "model_failed", "executor_parse_failed",
        "guard_parse_failed", "plan_revision_failed", "frontier_recovery_failed",
    }:
        add("environment_or_framework_failure",
            f"status={result.get('status')}: {result.get('error')}")

    node_counts = Counter((row.get("proposal") or {}).get("subgoal_id") for row in executor)
    node_counts.pop(None, None)
    if node_counts and max(node_counts.values()) >= 10:
        node, count = node_counts.most_common(1)[0]
        add("stuck_on_subgoal", f"{node} received {count} executor actions")

    unknown = [row for row in guards if row.get("judgement") == "unknown"]
    if len(unknown) >= 3:
        add("guard_unknown_without_next_evidence", f"unknown guard results={len(unknown)}")
    trace_no_gain = [row for row in _json_lines(directory / "execution_trace.jsonl")
                     if row.get("guard_judgement") == "unknown"
                     and not row.get("information_gain")]
    if len(trace_no_gain) >= 3:
        add("no_information_gain", f"unknown/no-gain trace entries={len(trace_no_gain)}")
    revisions = [row for row in contracts if row.get("from_contract")]
    unchanged = [row for row in revisions
                 if not row.get("evidence_sources_changed") and not row.get("verifier_changed")]
    if unchanged:
        add("contract_revision_without_verifier_change",
            f"unchanged contract revisions={len(unchanged)}")
    if revisions and not any(row.get("evidence_sources_changed") for row in revisions):
        add("repeated_evidence_source", "no accepted contract revision changed evidence source")

    if result.get("repair_cycle_count", 0) and not result.get("success"):
        add("repair_too_late_or_failed",
            f"repair cycles={result.get('repair_cycle_count')}, status={result.get('status')}")
    if result.get("local_replan_success_count", 0) and not result.get("success"):
        steps = [row.get("step") for row in patches]
        add("replan_operationally_ineffective",
            f"applied replans={result.get('local_replan_success_count')} at steps={steps}")
    if result.get("status") == "max_steps":
        add("step_budget_exhausted", f"total_steps={result.get('total_steps')}")

    interventions = []
    for row in trajectory:
        step = row.get("step")
        for event in row.get("interventions") or ():
            interventions.append({"step": step, **event})
    interventions.extend({"step": row.get("step"), "type": "local_replan",
                          "node_id": row.get("node_id")}
                         for row in patches)
    interventions.sort(key=lambda row: int(row.get("step") or 0))
    suspicious_steps = [row.get("step") for row in guards
                        if any(update.get("op") == "suspicious"
                               for update in row.get("state_updates") or ())]

    if not labels and not result.get("success"):
        add("unknown_or_ambiguous", "no deterministic taxonomy rule matched")
    primary = _dominant_label(labels)
    return {
        "status": result.get("status"),
        "success": bool(result.get("success")),
        "primary_failure_mode": None if result.get("success") else primary,
        "candidate_failure_modes": labels,
        "evidence": evidence,
        "earliest_suspicious_step": min(suspicious_steps) if suspicious_steps else None,
        "first_intervention": interventions[0] if interventions else None,
        "intervention_sequence": interventions,
        "steps": result.get("total_steps", 0),
        "guard_calls": result.get("guard_calls", 0),
        "unknown_count": result.get("unknown_checkpoint_count", 0),
        "repair_count": result.get("repair_cycle_count", 0),
        "replan_count": result.get("local_replan_count", 0),
        "replan_success_count": result.get("local_replan_success_count", 0),
        "verification_complete": _verification_complete(result),
    }


def _verification_complete(result) -> bool:
    nodes = (result.get("task_state") or {}).get("nodes", {})
    required = [node for node in nodes.values() if node.get("required", True)]
    return bool(required) and all(node.get("status") == "verified" and node.get("evidence")
                                  for node in required)


def _dominant_label(labels: list[str]) -> str | None:
    priority = (
        "environment_or_framework_failure", "wrong_subgoal_or_frontier",
        "missing_enter_or_incomplete_action", "premature_finish",
        "contract_revision_without_verifier_change", "no_information_gain",
        "replan_operationally_ineffective", "repair_too_late_or_failed",
        "stuck_on_subgoal", "excessive_wait", "step_budget_exhausted",
        "unknown_or_ambiguous",
    )
    return next((label for label in priority if label in labels), labels[0] if labels else None)


def _runs_of(values, target):
    run = []
    for value in values:
        if value == target:
            run.append(value)
        elif run:
            yield run
            run = []
    if run:
        yield run
