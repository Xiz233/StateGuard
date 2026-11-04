from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml

from experiments.poc.manifest_validation import has_placeholder, load_fault_manifest


def main():
    parser = argparse.ArgumentParser(description="Human review of controlled fault mutations")
    parser.add_argument("--manifest", default="configs/poc/fault_manifest.yaml")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    for item in load_fault_manifest(args.manifest):
        path = Path(item["spec_file"])
        spec = item["spec"]
        print(f"\n{item['task_id']} / {spec['fault_id']}\n"
              f"{yaml.safe_dump(spec, sort_keys=False)}")
        if has_placeholder(spec["inject"]["mutation"]):
            print(f"Edit concrete mutation coordinates/value in {path} before approval.")
            continue
        decision = input("approve/reject/skip: ").strip().lower()
        if decision == "skip":
            continue
        spec["manual_review"] = {
            **spec.get("manual_review", {}), "approved": decision == "approve",
            "approved_by": args.reviewer,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
