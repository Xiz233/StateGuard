from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


TARGETS = {"calc": 4, "writer": 3, "chrome": 3, "file": 2}


def discover(root: Path):
    tasks = []
    for path in sorted(root.rglob("*.json")):
        try: raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError): continue
        if not isinstance(raw, dict) or not (raw.get("instruction") or raw.get("task")): continue
        task_id = str(raw.get("id") or raw.get("task_id") or path.stem)
        app = str(raw.get("application") or raw.get("app") or "unknown").lower()
        tasks.append({"task_id": task_id, "instruction": raw.get("instruction", raw.get("task")),
                      "application": app, "evaluator": raw.get("evaluator"),
                      "setup_requirements": raw.get("setup", raw.get("config", [])),
                      "source": str(path), "eligible": bool(raw.get("evaluator"))})
    return tasks


def select(tasks, seed=20260814):
    rng, groups = random.Random(seed), defaultdict(list)
    for task in tasks:
        if not task["eligible"]: continue
        app = task["application"]
        key = next((k for k in TARGETS if k in app), "file" if "file" in app else None)
        if key: groups[key].append(task)
    chosen = []
    for key, count in TARGETS.items():
        pool = sorted(groups[key], key=lambda t: t["task_id"]); rng.shuffle(pool); chosen += pool[:count]
    return sorted(chosen, key=lambda t: t["task_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--output", default="configs/tasks/osworld")
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()
    root, output = Path(args.benchmark_root), Path(args.output)
    if not root.exists(): raise ValueError(f"benchmark root does not exist: {root}")
    artifacts = Path("artifacts/task_discovery"); artifacts.mkdir(parents=True, exist_ok=True)
    all_tasks = discover(root); eligible = [t for t in all_tasks if t["eligible"]]
    selected = select(all_tasks, args.seed)
    for name, value in (("all_tasks.json", all_tasks), ("eligible_tasks.json", eligible)):
        (artifacts / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    report = ["# OSWorld task selection", "", f"Discovered: {len(all_tasks)}",
              f"Eligible: {len(eligible)}", f"Selected: {len(selected)}", ""]
    report += [f"- {t['task_id']}: {t['application']}" for t in selected]
    (artifacts / "selection_report.md").write_text("\n".join(report), encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    import yaml
    manifest = {"seed": args.seed, "tasks": [{**t, "graph_file":
        str(output / f"{t['task_id']}.json")} for t in selected]}
    Path("configs/poc/selected_tasks.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))


if __name__ == "__main__": main()
