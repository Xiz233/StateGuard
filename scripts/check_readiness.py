from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from stateguard.models import load_model_config


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


def _endpoint_ready(provider) -> bool:
    if not provider.base_url or not provider.model or not os.getenv(provider.api_key_env):
        return False
    key = os.getenv(provider.api_key_env)
    headers = ({"x-api-key": key, "anthropic-version": "2023-06-01"}
               if provider.type == "anthropic_compatible" else
               {"Authorization": f"Bearer {key}"})
    headers.update(provider.extra_headers)
    request = urllib.request.Request(provider.base_url.rstrip("/") + "/models",
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=min(provider.timeout_seconds, 10)) as response:
            models = json.loads(response.read()).get("data", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return False
    return any(item.get("id") == provider.model for item in models)


def _readiness(backend="real", config="configs/models.yaml", osworld_root=None):
    core = {name: Path(path).exists() for name, path in CORE_CHECKS.items()}
    if backend == "fake":
        from experiments.poc.config import load_config
        from experiments.poc.runner import validate_experiment
        fake = load_config("configs/poc/fake_osworld.yaml")
        validate_experiment(fake, allow_dirty=True)
        external = {"Fake backend": True, "Fake task assets": True, "Mock providers": True}
    else:
        providers = load_model_config(config) if Path(config).exists() else {}
        guard = providers.get("stateguard_api")
        executor = providers.get("executor_qwen")
        root = Path(osworld_root or os.getenv("OSWORLD_ROOT", ""))
        external = {
            "StateGuard API endpoint": bool(guard and _endpoint_ready(guard)),
            "Qwen32B endpoint": bool(executor and executor.model == "Qwen3-VL-32B-Instruct"
                                     and _endpoint_ready(executor)),
            "OSWorld installation": (importlib.util.find_spec("desktop_env") is not None or
                                     (root / "desktop_env" / "desktop_env.py").exists()),
            "OSWorld task assets": Path("configs/poc/selected_tasks.yaml").exists(),
        }
    return core, external


def readiness(config="configs/models.yaml", osworld_root=None):
    """Backward-compatible machine-readable summary."""
    core, external = _readiness("real", config, osworld_root)
    return {"Core StateGuard": ("READY" if all(core.values()) else "NOT READY", "core checks"),
            "StateGuard API": ("READY" if external["StateGuard API endpoint"] else
                               "NOT CONFIGURED", config),
            "Executor Qwen endpoint": ("READY" if external["Qwen32B endpoint"] else
                                       "NOT CONFIGURED", "Qwen3-VL-32B-Instruct"),
            "OSWorld": ("READY" if external["OSWorld installation"] else "NOT AVAILABLE",
                        "external benchmark")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("real", "fake"), default="real")
    parser.add_argument("--config", default="configs/models.yaml")
    parser.add_argument("--osworld-root")
    args = parser.parse_args()
    core, external = _readiness(args.backend, args.config, args.osworld_root)
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
