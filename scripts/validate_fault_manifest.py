from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import yaml

from experiments.poc.manifest_validation import (
    load_fault_manifest, load_graph, validate_distribution, validate_fault,
)


def main():
    parser = argparse.ArgumentParser(description="Validate and attach approved PoC faults")
    parser.add_argument("--task-manifest", default="configs/poc/selected_tasks.yaml")
    parser.add_argument("--fault-manifest", default="configs/poc/fault_manifest.yaml")
    parser.add_argument("--attach-output", default="configs/poc/selected_tasks_ready.yaml")
    parser.add_argument("--allow-unapproved", action="store_true")
    args = parser.parse_args()
    manifest = yaml.safe_load(Path(args.task_manifest).read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    by_task = {task["task_id"]: task for task in tasks}
    faults = load_fault_manifest(args.fault_manifest)
    validate_distribution(faults)
    attached = defaultdict(list)
    for item in faults:
        task = by_task.get(item["task_id"])
        if not task:
            raise ValueError(f"fault references unknown task {item['task_id']}")
        _, graph = load_graph(task["graph_file"])
        validate_fault(item["spec"], graph, require_approved=not args.allow_unapproved)
        attached[item["task_id"]].append(item["spec"])
    if not args.allow_unapproved:
        output = {**manifest, "fault_manifest": args.fault_manifest,
                  "tasks": [{**task, "faults": attached[task["task_id"]]} for task in tasks]}
        Path(args.attach_output).write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    print("FAULT_MANIFEST_READY" if not args.allow_unapproved else "FAULT_DRAFT_STRUCTURE_READY")


if __name__ == "__main__":
    main()
