from __future__ import annotations

import argparse
import json

from experiments.poc import MODES
from experiments.poc.config import load_config
from experiments.poc.runner import run_experiment


def main():
    parser = argparse.ArgumentParser(description="StateGuard OSWorld PoC runner")
    parser.add_argument("--config", default="configs/poc/osworld_poc.yaml")
    parser.add_argument("--models", default="configs/models.yaml")
    parser.add_argument("--mode", choices=sorted(MODES), default="stateguard")
    parser.add_argument(
        "--tasks", default="all",
        help="Run all tasks or a comma-separated list of exact task ids",
    )
    parser.add_argument("--task")
    parser.add_argument(
        "--scenario",
        default="all",
        help="Run all scenarios, only clean, or one exact fault_id",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    selected = args.task or args.tasks
    result = run_experiment(load_config(args.config), args.mode, selected,
                            args.resume, args.rerun_failed, args.dry_run,
                            args.allow_dirty, args.models, args.scenario)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
