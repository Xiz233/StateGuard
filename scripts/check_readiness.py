from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


CORE_CHECKS = {
    "Phase-I tests": "tests/test_task_state.py",
    "Model client": "stateguard/models/openai_compatible.py",
    "Guard backend": "stateguard/guard/backends/hybrid_backend.py",
    "Executor": "stateguard/executor/mllm_executor.py",
    "Repair loop": "stateguard/runtime/episode_runner.py",
    "Fault injection": "experiments/poc/faults/scheduler.py",
    "Experiment runner": "experiments/poc/runner.py",
    "Logging": "experiments/poc/logging.py",
    "Metrics": "experiments/poc/metrics.py",
}


def _readiness(backend="real", config="configs/models.yaml"):
    core = {name: Path(path).exists() for name, path in CORE_CHECKS.items()}
    if backend == "fake":
        from experiments.poc.config import load_config
        from experiments.poc.runner import validate_experiment
        fake = load_config("configs/poc/fake_osworld.yaml")
        validate_experiment(fake, allow_dirty=True)
        external = {"Fake backend": True, "Fake task assets": True, "Mock providers": True}
    else:
        external = {
            "StateGuard API credential": all(os.getenv(k) for k in
                ("STATEGUARD_API_KEY", "STATEGUARD_BASE_URL", "STATEGUARD_MODEL")),
            "Qwen32B endpoint": all(os.getenv(k) for k in
                ("EXECUTOR_BASE_URL", "EXECUTOR_API_KEY", "EXECUTOR_MODEL")),
            "OSWorld installation": importlib.util.find_spec("desktop_env") is not None,
            "OSWorld task assets": Path("configs/poc/selected_tasks.yaml").exists(),
        }
    return core, external


def readiness(config="configs/models.yaml"):
    """Backward-compatible machine-readable summary."""
    core, external = _readiness("real", config)
    return {"Core StateGuard": ("READY" if all(core.values()) else "NOT READY", "core checks"),
            "StateGuard API": ("READY" if external["StateGuard API credential"] else
                               "NOT CONFIGURED", config),
            "Executor Qwen endpoint": ("READY" if external["Qwen32B endpoint"] else
                                       "NOT CONFIGURED", "Qwen3-VL-32B-Instruct"),
            "OSWorld": ("READY" if external["OSWorld installation"] else "NOT AVAILABLE",
                        "external benchmark")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("real", "fake"), default="real")
    parser.add_argument("--config", default="configs/models.yaml")
    args = parser.parse_args()
    core, external = _readiness(args.backend, args.config)
    print("CORE CODE")
    for name, ready in core.items(): print(f"[{'READY' if ready else 'NOT_READY'}] {name}")
    print("\nEXTERNAL" if args.backend == "real" else "\nFAKE DEPLOYMENT")
    for name, ready in external.items():
        label = "READY" if ready else "BLOCKED_EXTERNAL"
        print(f"[{label}] {name}")
    fully = all(core.values()) and all(external.values())
    final = "FULLY_READY" if fully else "CODE_READY_EXTERNAL_DEPLOYMENT_PENDING"
    print(f"\nFINAL:\n{final}")
    if not all(core.values()): sys.exit(1)


if __name__ == "__main__": main()
