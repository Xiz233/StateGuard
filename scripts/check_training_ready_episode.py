#!/usr/bin/env python3
"""Validate the raw-evidence invariants of training-ready episode logs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def check_episode(directory: Path) -> dict:
    errors, warnings = [], []
    events = _rows(directory / "events.jsonl")
    calls = _rows(directory / "model_calls.jsonl")
    artifacts = _rows(directory / "artifact_manifest.jsonl")
    phases = defaultdict(set)
    for event in events:
        if event.get("event_phase"):
            phases[event.get("event_id")].add(event["event_phase"])

    logical = [event for event in events if event.get("event_phase") == "started"]
    for event in logical:
        terminal = phases[event["event_id"]] & {"completed", "failed", "cancelled"}
        if not terminal:
            errors.append(f"unclosed logical event {event['event_id']}")

    call_rows = [row for row in calls if row.get("record_type") == "call"]
    call_starts = {row.get("call_id") for row in calls
                   if row.get("record_type") == "call_started"}
    terminal_call_ids = {row.get("call_id") for row in call_rows}
    for call_id in sorted(call_starts - terminal_call_ids):
        errors.append(f"model call {call_id} started but has no terminal record")
    parse_updates = defaultdict(list)
    for row in calls:
        if row.get("record_type") == "parse_update":
            parse_updates[row.get("call_id")].append(row)
    for call in call_rows:
        if call_starts and call.get("call_id") not in call_starts:
            errors.append(f"model call {call.get('call_id')} has no started record")
        if not call.get("request", {}).get("messages"):
            errors.append(f"model call {call.get('call_id')} has no exact messages")
        if not call.get("raw_text") and not call.get("error"):
            errors.append(f"model call {call.get('call_id')} has no response or failure")
        if call.get("status") == "completed" and not parse_updates[call.get("call_id")]:
            warnings.append(f"model call {call.get('call_id')} has no domain parse update")

    transitions = [event for event in events
                   if event.get("event_type") == "environment_transition"
                   and event.get("event_phase") in {"completed", "failed"}]
    for event in transitions:
        receipt = event.get("execution_receipt")
        if not receipt:
            errors.append(f"transition {event.get('event_id')} has no execution receipt")
        if event.get("task_state_before") is None or event.get("task_state_after") is None:
            errors.append(f"transition {event.get('event_id')} lacks state boundary")
        if event.get("state_delta") is None:
            errors.append(f"transition {event.get('event_id')} lacks state delta")

    artifact_ids = {row.get("artifact_id") for row in artifacts}
    artifact_locations = defaultdict(set)
    referenced_ids = set()
    for event in events:
        for key, value in event.items():
            if key.endswith("artifact_id") and value:
                referenced_ids.add(value)
    for call in call_rows:
        referenced_ids.update(value for value in call.get("image_artifact_ids", []) if value)
    missing_artifacts = sorted(referenced_ids - artifact_ids)
    if missing_artifacts:
        errors.append(f"missing artifact manifest rows: {missing_artifacts}")
    for artifact in artifacts:
        path = directory / artifact.get("relative_path", "")
        artifact_locations[artifact.get("artifact_id")].add(
            artifact.get("relative_path"))
        if not path.is_file():
            errors.append(f"artifact file missing: {artifact.get('artifact_id')}")
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != artifact.get("sha256"):
            errors.append(f"artifact hash mismatch: {artifact.get('artifact_id')}")
        if len(data) != artifact.get("byte_size"):
            errors.append(f"artifact size mismatch: {artifact.get('artifact_id')}")
    for artifact_id, locations in artifact_locations.items():
        if len(locations) != 1:
            errors.append(
                f"artifact {artifact_id} maps to multiple paths: {sorted(locations)}")

    finish = [event for event in events if event.get("event_type") == "finish_decision"
              and event.get("event_phase") in {"completed", "failed"}]
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    if result.get("status") == "completed" and not finish:
        errors.append("finish decision is missing")
    elif not finish:
        warnings.append("episode terminated without a finish decision")

    evaluator_path = directory / "evaluator_result.json"
    evaluator = json.loads(evaluator_path.read_text()) if evaluator_path.exists() else None
    if evaluator is None:
        errors.append("evaluator_result.json is missing")
    elif evaluator.get("exception") is None and evaluator.get("details") is None:
        errors.append("successful evaluator call has no details")

    unknown_indices = [index for index, event in enumerate(events)
                       if (event.get("guard_result") or {}).get("judgement") == "unknown"]
    unresolved_unknowns = sum(
        not any(later.get("event_phase") in {"completed", "failed"}
                for later in events[index + 1:])
        for index in unknown_indices)
    if unresolved_unknowns:
        errors.append(f"{unresolved_unknowns} UNKNOWN event(s) have no later event")

    resolution_rows = _rows(directory / "unknown_resolutions.jsonl")
    if resolution_rows:
        opened = {row.get("unknown_event_id") for row in resolution_rows
                  if row.get("record_type") == "unknown_opened"}
        resolved = {row.get("unknown_event_id") for row in resolution_rows
                    if row.get("record_type") == "unknown_resolved"}
        if opened - resolved:
            errors.append(f"UNKNOWN outcomes missing: {sorted(opened - resolved)}")
        if len(opened) != len(unknown_indices):
            errors.append(
                f"UNKNOWN sidecar count {len(opened)} != event count {len(unknown_indices)}")

    roles = sorted({call.get("role") for call in call_rows if call.get("role")})
    return {
        "episode": str(directory),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "logical_events": len(logical),
            "model_calls": len(call_rows),
            "environment_transitions": len(transitions),
            "artifacts": len(artifacts),
            "unknown_events": len(unknown_indices),
            "finish_events": len(finish),
        },
        "model_roles": roles,
        "evaluator": evaluator,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    results = [check_episode(Path(path)) for path in args.episodes]
    report = {"passed": all(result["passed"] for result in results),
              "episodes": results}
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
