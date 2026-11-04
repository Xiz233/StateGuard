#!/usr/bin/env python3
"""Summarize UNKNOWN, parser, budget, and lifecycle stability metrics."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from stateguard.verification.unknowns import classify_unknown_type


def legacy_failure_type(row):
    error = str(row.get("parse_error") or "").lower()
    if "missing required fields" in error:
        return "schema_missing_fields"
    if "blocked after repeated" in error:
        return "policy_blocked_action"
    if "outside the executable frontier" in error:
        return "policy_frontier_violation"
    if "new_nodes must contain" in error or "replacement" in error:
        return "schema_or_semantic_validation"
    return "unclassified"


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()] if path.exists() else []


def analyze(root: Path) -> dict:
    episodes = [path for path in root.iterdir() if path.is_dir()]
    status = Counter()
    unknown_types = Counter()
    resolutions = Counter()
    parse = Counter()
    calls = Counter()
    intervention_types = Counter()
    missing_hindsight = 0
    totals = Counter()
    per_episode = []
    for episode in episodes:
        result_path = episode / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        status[result.get("status")] += 1
        episode_unknown = 0
        model_rows = rows(episode / "model_calls.jsonl")
        for row in model_rows:
            if row.get("record_type") == "call":
                calls[row.get("role")] += 1
                totals["model_calls"] += 1
            elif row.get("record_type") == "parse_update" \
                    and row.get("parse_status") in {"failed", "rejected", "fallback"}:
                parse[(row.get("parse_status"),
                       row.get("failure_type") or legacy_failure_type(row))] += 1
        unknown_rows = rows(episode / "unknown_resolutions.jsonl")
        if unknown_rows:
            for row in unknown_rows:
                if row.get("record_type") == "unknown_opened":
                    unknown_types[row.get("unknown_type") or "unclassified"] += 1
                    totals["unknown"] += 1
                    episode_unknown += 1
                elif row.get("record_type") == "unknown_resolved":
                    resolutions[(row.get("resolution"), row.get("resolution_source"))] += 1
        else:
            for row in rows(episode / "guard_events.jsonl"):
                if row.get("judgement") == "unknown":
                    unknown_types[classify_unknown_type(row)] += 1
                    totals["unknown"] += 1
                    episode_unknown += 1
        interventions = rows(episode / "interventions.jsonl")
        opened = {row.get("intervention_id") for row in interventions
                  if row.get("record_type") != "hindsight_outcome"}
        closed = {row.get("intervention_id") for row in interventions
                  if row.get("record_type") == "hindsight_outcome"}
        missing_hindsight += len(opened - closed)
        for row in interventions:
            if row.get("record_type") != "hindsight_outcome":
                intervention_types[row.get("intervention_type")] += 1
        per_episode.append({
            "episode": episode.name,
            "status": result.get("status"),
            "success": result.get("success"),
            "steps": result.get("total_steps"),
            "unknown": episode_unknown,
            "max_consecutive_unknown": result.get("max_consecutive_unknown_observed"),
            "error": result.get("error"),
        })
    return {
        "episodes_completed": len(per_episode),
        "status_counts": dict(status),
        "model_calls_by_role": dict(calls),
        "parse_outcomes": {f"{key[0]}:{key[1]}": value for key, value in parse.items()},
        "unknown_types": dict(unknown_types),
        "unknown_resolutions": {
            f"{key[0]}:{key[1]}": value for key, value in resolutions.items()},
        "interventions": dict(intervention_types),
        "interventions_missing_hindsight": missing_hindsight,
        "per_episode": per_episode,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = analyze(Path(args.root))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
