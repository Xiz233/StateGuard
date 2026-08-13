from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path


def readiness(config="configs/models.yaml"):
    config_path = Path(config)
    if not config_path.exists():
        example = Path("configs/models.example.yaml")
        config_path = example if example.exists() else config_path
    graph_dir = Path("configs/tasks/osworld")
    return {
        "Core StateGuard": ("READY", "package importable"),
        "StateGuard API": ("READY" if all(os.getenv(k) for k in
                               ("STATEGUARD_API_KEY", "STATEGUARD_BASE_URL", "STATEGUARD_MODEL"))
                           else "NOT CONFIGURED", str(config_path)),
        "Executor Qwen endpoint": ("READY" if os.getenv("EXECUTOR_BASE_URL") else
                                    "NOT CONFIGURED", "Qwen3-VL-32B-Instruct"),
        "OSWorld": ("READY" if importlib.util.find_spec("desktop_env") else
                    "NOT AVAILABLE", "optional on this server"),
        "Manual task graphs": ("READY" if graph_dir.exists() and any(graph_dir.glob("*.json"))
                               else "OPTIONAL", str(graph_dir)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/models.yaml")
    args = parser.parse_args()
    for name, (status, detail) in readiness(args.config).items():
        print(f"{name}: {status} ({detail})")


if __name__ == "__main__":
    main()
