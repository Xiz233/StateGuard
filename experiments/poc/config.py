from pathlib import Path

import yaml


def load_config(path):
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    required = {"experiment", "runtime", "environment", "executor", "guard",
                "task_graph", "evaluation"}
    missing = required - value.keys()
    if missing: raise ValueError(f"experiment config missing {sorted(missing)}")
    design = value["experiment"].get("design", "controlled_fault_diagnostic")
    if design not in {"natural_failure", "controlled_fault_diagnostic"}:
        raise ValueError(f"unsupported experiment design {design!r}")
    if design == "controlled_fault_diagnostic" and "faults" not in value:
        raise ValueError("controlled fault diagnostic config requires faults")
    return value
