from pathlib import Path

import yaml


def load_config(path):
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    required = {"experiment", "runtime", "environment", "executor", "guard",
                "task_graph", "faults", "evaluation"}
    missing = required - value.keys()
    if missing: raise ValueError(f"experiment config missing {sorted(missing)}")
    return value
