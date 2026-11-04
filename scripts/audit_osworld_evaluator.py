#!/usr/bin/env python3
"""Run native OSWorld evaluators and capture adapter component probes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from integrations.osworld.adapter import DesktopEnvBackend


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_configs", nargs="+")
    parser.add_argument("--osworld-root", required=True)
    parser.add_argument("--vm-path", required=True)
    parser.add_argument("--provider", default="docker")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    backend = DesktopEnvBackend(
        provider=args.provider,
        headless=args.headless,
        osworld_root=args.osworld_root,
        path_to_vm=args.vm_path,
        cache_dir=args.cache_dir,
        require_a11y_tree=False,
        enable_proxy=False,
        client_password="password",
    )
    records = []
    try:
        for value in args.task_configs:
            path = Path(value)
            task = json.loads(path.read_text(encoding="utf-8"))
            record = {
                "task_id": task.get("id"),
                "task_config_path": str(path),
                "application": path.parent.name,
                "instruction": task.get("instruction"),
                "evaluator_definition": task.get("evaluator"),
                "reset_seconds": None,
                "evaluate_seconds": None,
                "result": None,
                "exception": None,
            }
            try:
                started = time.monotonic()
                backend.reset({"task_config_path": str(path)})
                record["reset_seconds"] = time.monotonic() - started
                started = time.monotonic()
                result = backend.evaluate({"task_config_path": str(path)})
                record["evaluate_seconds"] = time.monotonic() - started
                record["result"] = {
                    "success": result.success,
                    "score": result.score,
                    "details": result.details,
                }
            except Exception as exc:
                record["exception"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            output.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    finally:
        backend.close()
    print(json.dumps(records, indent=2, default=str))


if __name__ == "__main__":
    main()
