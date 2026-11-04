from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from experiments.poc.manifest_validation import load_graph


def mutation_for(fault_type: str) -> dict:
    if fault_type in {"wrong_target", "earlier_state_corruption"}:
        return {"action_override": {"type": "click", "x": "REVIEW_REQUIRED",
                                    "y": "REVIEW_REQUIRED"}}
    if fault_type == "wrong_value":
        return {"replace_text": "REVIEW_REQUIRED"}
    return {}


def main():
    parser = argparse.ArgumentParser(description="Create 24 manually-reviewable PoC fault drafts")
    parser.add_argument("--manifest", default="configs/poc/selected_tasks.yaml")
    parser.add_argument("--output", default="configs/faults/osworld")
    parser.add_argument("--fault-manifest", default="configs/poc/fault_manifest.yaml")
    args = parser.parse_args()
    tasks = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))["tasks"]
    if len(tasks) != 12:
        raise ValueError(f"expected 12 selected tasks, got {len(tasks)}")
    graph_data = {}
    for task in tasks:
        raw, graph = load_graph(task["graph_file"])
        if not raw.get("graph", {}).get("approved"):
            raise ValueError(f"DAG must be manually approved first: {task['graph_file']}")
        graph_data[task["task_id"]] = graph
    earlier_tasks = [task for task in tasks
                     if len(graph_data[task["task_id"]].nodes()) >= 4 and
                     any(graph_data[task["task_id"]].descendants(node)
                         for node in graph_data[task["task_id"]].nodes())]
    if len(earlier_tasks) < 6:
        raise ValueError("at least six selected tasks need >=4 DAG nodes for balanced earlier corruption")
    earlier_ids = {task["task_id"] for task in earlier_tasks[:6]}
    remaining_types = iter([fault_type for _ in range(6) for fault_type in
                            ("wrong_target", "wrong_value", "no_effect")])
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for task in tasks:
        graph = graph_data[task["task_id"]]
        types = ["earlier_state_corruption", next(remaining_types)] if task["task_id"] in earlier_ids else [next(remaining_types), next(remaining_types)]
        order = graph.topological_order()
        for index, fault_type in enumerate(types, 1):
            if fault_type == "earlier_state_corruption":
                roots = [node for node in order[1:] if graph.descendants(node)]
                root = roots[0] if roots else next(
                    node for node in order if graph.descendants(node)
                )
            else:
                root = order[min(index - 1, len(order) - 1)]
            affected = [root] + graph.descendants(root)
            preserved = [node for node in order if node not in affected]
            exposure = ({"mode": "delayed", "trigger": {"subgoal_id": affected[-1]}}
                        if fault_type == "earlier_state_corruption" else {"mode": "immediate"})
            fault_id = f"{task['task_id']}--{fault_type}--{index}"
            spec = {
                "fault_id": fault_id, "type": fault_type, "root_node": root,
                "inject": {"trigger": {"subgoal_id": root, "occurrence": 1},
                           "mutation": mutation_for(fault_type)},
                "exposure": exposure, "expected_affected": affected,
                "expected_preserved": preserved,
                "manual_review": {"approved": False, "approved_by": None,
                                  "approved_at": None,
                                  "notes": "Confirm trigger, concrete mutation, and exposure visually."},
            }
            path = output / f"{fault_id}.yaml"
            path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
            entries.append({"task_id": task["task_id"], "spec_file": str(path)})
    manifest = {"source_task_manifest": args.manifest, "faults": entries}
    Path(args.fault_manifest).write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    print(json.dumps({"faults": len(entries), "manifest": args.fault_manifest}, indent=2))


if __name__ == "__main__":
    main()
