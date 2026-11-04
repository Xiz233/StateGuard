"""Build a semantic action catalog and fault-trigger audit from clean runs."""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _task_id(path: str) -> str:
    return Path(path).parent.name.split("--", 1)[0]


def build_catalog(trajectories: list[str], manifest: dict) -> dict:
    manifest_tasks = {task["task_id"]: task for task in manifest.get("tasks", [])}
    tasks = {}
    for path in sorted(trajectories):
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        actions = []
        grouped = defaultdict(list)
        for row in rows:
            proposal = row.get("executor_proposal") or {}
            action = row.get("executed_action") or proposal.get("action") or {}
            item = {
                "step": row["step"],
                "subgoal_id": proposal.get("subgoal_id"),
                "action_type": action.get("type") if isinstance(action, dict) else None,
                "action": action,
                "intent": proposal.get("intent", ""),
                "subgoal_done": bool(proposal.get("subgoal_done", False)),
            }
            actions.append(item)
            grouped[item["subgoal_id"]].append(item)
        task_id = _task_id(path)
        result_path = Path(path).with_name("result.json")
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        record = {
            "trajectory": path,
            "result_path": str(result_path) if result_path.exists() else None,
            "run_status": result.get("status"),
            "task_success": result.get("success"),
            "environment_score": result.get("environment_score"),
            "action_count": len(actions),
            "actions": actions,
            "by_subgoal": {
                node_id: {
                    "action_count": len(items),
                    "action_types": dict(Counter(i["action_type"] for i in items)),
                }
                for node_id, items in sorted(grouped.items())
            },
        }
        triggers = [fault["inject"]["trigger"]
                    for fault in manifest_tasks.get(task_id, {}).get("faults", [])]
        coverage = 0
        for trigger in triggers:
            matches = [item for item in actions
                       if item["subgoal_id"] == trigger["subgoal_id"]
                       and (not trigger.get("action_type")
                            or item["action_type"] == trigger["action_type"])]
            coverage += int(len(matches) >= int(trigger.get("occurrence", 1)))
        record["fault_trigger_coverage"] = coverage
        previous = tasks.get(task_id)
        rank = (coverage, bool(result.get("success")), len(actions))
        previous_rank = ((previous["fault_trigger_coverage"],
                          bool(previous["task_success"]), previous["action_count"])
                         if previous else None)
        if previous_rank is None or rank > previous_rank:
            tasks[task_id] = record

    audit = []
    for task in manifest.get("tasks", []):
        task_id = task["task_id"]
        clean_actions = tasks.get(task_id, {}).get("actions", [])
        for fault in task.get("faults", []):
            trigger = fault["inject"]["trigger"]
            matches = [
                item for item in clean_actions
                if item["subgoal_id"] == trigger["subgoal_id"]
                and (not trigger.get("action_type")
                     or item["action_type"] == trigger["action_type"])
            ]
            occurrence = int(trigger.get("occurrence", 1))
            audit.append({
                "task_id": task_id,
                "fault_id": fault["fault_id"],
                "fault_type": fault["type"],
                "trigger": trigger,
                "valid": len(matches) >= occurrence,
                "matching_action_count": len(matches),
                "selected_action": matches[occurrence - 1] if len(matches) >= occurrence else None,
            })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_count": len(tasks),
        "tasks": tasks,
        "fault_trigger_audit": audit,
        "trigger_validity_rate": (
            sum(item["valid"] for item in audit) / len(audit) if audit else 1.0),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory-glob", action="append")
    parser.add_argument("--manifest", default="configs/poc/selected_tasks_ready.yaml")
    parser.add_argument(
        "--output",
        default="/data/research/stateguard_runs/round2_5/clean_trajectory_catalog.json")
    args = parser.parse_args()
    manifest = yaml.safe_load(Path(args.manifest).read_text()) or {}
    patterns = args.trajectory_glob or [
        "/data/research/stateguard_runs/poc_v1_108/"
        "osworld_stateguard_poc-stateguard/episodes/"
        "*--stateguard--clean/trajectory.jsonl"]
    trajectories = [path for pattern in patterns
                    for path in glob.glob(pattern, recursive=True)
                    if Path(path).with_name("result.json").exists()]
    catalog = build_catalog(trajectories, manifest)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    valid = sum(item["valid"] for item in catalog["fault_trigger_audit"])
    total = len(catalog["fault_trigger_audit"])
    print(f"tasks={catalog['task_count']} triggers={valid}/{total} "
          f"validity={catalog['trigger_validity_rate']:.3f}")
    print(args.output)


if __name__ == "__main__":
    main()
