from __future__ import annotations

import argparse

from experiments.poc import MODES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/poc/osworld_tasks.yaml")
    parser.add_argument("--mode", choices=sorted(MODES), default="stateguard")
    args = parser.parse_args()
    raise SystemExit(f"OSWorld endpoint/tasks not available; mode={args.mode}, config={args.config}")


if __name__ == "__main__":
    main()
