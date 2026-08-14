from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from stateguard.compiler.manual_loader import load_manual_task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="configs/poc/selected_tasks.yaml")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approve-all", action="store_true")
    args = parser.parse_args()
    tasks = yaml.safe_load(Path(args.manifest).read_text())["tasks"]
    for task in tasks:
        path = Path(task["graph_file"]); raw = json.loads(path.read_text())
        print(f"\n{task['task_id']}: {task['instruction']}\n{json.dumps(raw['nodes'], indent=2)}")
        decision = "approve" if args.approve_all else input("approve/edit/reject: ").strip().lower()
        if decision == "edit":
            print(f"Edit {path}, then rerun review."); continue
        raw["graph"] = {"approved": decision == "approve", "approved_by": args.reviewer,
                        "approved_at": datetime.now(timezone.utc).isoformat() if decision == "approve" else None}
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        if decision == "approve": load_manual_task(path)


if __name__ == "__main__": main()
