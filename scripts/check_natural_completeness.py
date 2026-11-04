#!/usr/bin/env python3
"""Fail closed when a natural-failure experiment is incomplete or malformed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FRAMEWORK_FAILURES = {
    "environment_failed", "model_failed", "executor_parse_failed",
    "guard_parse_failed", "plan_revision_failed", "auto_dag_failed",
    "frontier_recovery_failed",
}


def check(root: str | Path, expected: int, allow_framework_failures=False):
    directory = Path(root)
    episode_dirs = sorted(path for path in directory.iterdir() if path.is_dir()) \
        if directory.exists() else []
    result_paths = sorted(directory.glob("*/result.json")) if directory.exists() else []
    errors = []
    if len(result_paths) != expected:
        errors.append(f"expected {expected} result.json files, found {len(result_paths)}")
    incomplete = [path.name for path in episode_dirs if not (path / "result.json").exists()]
    if incomplete:
        errors.append(f"episode directories without result.json: {incomplete}")
    for path in result_paths:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid result {path}: {exc}")
            continue
        metrics = result.get("metrics") or {}
        if metrics.get("experiment_design") != "natural_failure":
            errors.append(f"not a natural-failure result: {path}")
        if result.get("fault_events") or result.get("failure_exposure_events"):
            errors.append(f"artificial fault event found in natural run: {path}")
        if (path.parent / "fault_spec.json").exists():
            errors.append(f"legacy fault_spec.json found in natural run: {path.parent}")
        if not (path.parent / "trajectory.jsonl").exists():
            errors.append(f"missing trajectory: {path.parent}")
        if not (path.parent / "execution_trace.jsonl").exists():
            errors.append(f"missing execution trace: {path.parent}")
        if not allow_framework_failures and result.get("status") in FRAMEWORK_FAILURES:
            errors.append(
                f"framework failure {result.get('status')} in {path.parent.name}: "
                f"{result.get('error')}")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True)
    parser.add_argument("--expected", required=True, type=int)
    parser.add_argument("--allow-framework-failures", action="store_true")
    args = parser.parse_args()
    errors = check(args.episodes, args.expected, args.allow_framework_failures)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"complete: {args.expected} natural-failure episodes")


if __name__ == "__main__":
    main()
