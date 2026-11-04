from __future__ import annotations

import argparse
import json

from experiments.poc.config import load_config
from experiments.poc.runner import run_experiment


MODES = ("executor_only", "latest_retry", "stateguard")


def main():
    parser = argparse.ArgumentParser(description="Run the controlled 36x3 StateGuard PoC matrix")
    parser.add_argument("--config", default="configs/poc/osworld_poc.yaml")
    parser.add_argument("--models", default="configs/models.yaml")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    summaries = {}
    for mode in MODES:
        summary = run_experiment(config, mode, "all", args.resume, args.rerun_failed,
                                 args.dry_run, args.allow_dirty, args.models)
        if not args.dry_run and summary.get("episodes") != 36:
            raise RuntimeError(f"{mode}: expected 36 episodes, got {summary.get('episodes')}")
        summaries[mode] = summary
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
