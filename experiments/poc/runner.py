from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path

from stateguard.compiler.manual_loader import load_manual_task
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds
from stateguard.guard.backends import HybridBackend, MLLMBackend, RuleBackend
from stateguard.guard.state_guard import StateGuard
from stateguard.models import OpenAICompatibleModelClient, load_model_config
from stateguard.models.mock import MockModelClient
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.runtime.history import ActionHistory
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter

from .faults import make_injector
from .logging import RunLogger, digest, git_metadata
from .metrics import episode_metrics


def _executor_policy(task, mode):
    ordered, cursor, retrying = list(task["actions"]), [0], [False]
    def policy(messages, images, schema):
        payload = json.loads(messages[0]["content"])
        if mode == "stateguard":
            nodes = payload["task_state"]["nodes"]
            node_id = next((nid for nid in ordered if nodes[nid]["status"] != "verified"), None)
        else:
            repair = payload.get("repair", "")
            if repair and not retrying[0] and cursor[0] > 0:
                node_id, retrying[0] = ordered[cursor[0] - 1], True
            else:
                node_id = ordered[cursor[0]] if cursor[0] < len(ordered) else None
                if node_id: cursor[0] += 1
        if node_id is None:
            return {"subgoal_id": "", "intent": "finish", "expected_effect": "done",
                    "action": {}, "is_finish": True}
        return {"subgoal_id": node_id, "intent": f"complete {node_id}",
                "expected_effect": "task state advances", "action": task["actions"][node_id],
                "is_finish": False}
    return policy


def _guard_policy(messages, images, schema):
    payload = json.loads(messages[0]["content"])
    subgoal = payload["proposal"]["subgoal_id"]
    state = payload["after"].get("structured_state") or {}
    if subgoal == "S2" and state.get("target") == "bad":
        return {"judgement": "contradicted", "progress_updates": [], "fault_root": "S1",
                "fault_type": "wrong_target", "verification_target": None,
                "reason": "The value is in the wrong target; the earliest invalid state is S1."}
    return {"judgement": "verified", "progress_updates": [{"node_id": subgoal,
            "status": "verified", "evidence": f"Visible state supports {subgoal}."}],
            "fault_root": None, "fault_type": None, "verification_target": None,
            "reason": "Visible transition is consistent."}


def _real_client(provider, models_path):
    return OpenAICompatibleModelClient(load_model_config(models_path)[provider])


def validate_graph(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    approval = raw.get("graph", {})
    if not approval.get("approved") or not approval.get("approved_by") or not approval.get("approved_at"):
        raise ValueError(f"manual DAG is not approved: {path}")
    load_manual_task(path)
    return raw


def validate_experiment(config, allow_dirty=False):
    backend = config["environment"]["backend"]
    if backend != "fake" and git_metadata()["dirty_working_tree"] and not allow_dirty:
        raise ValueError("formal experiment requires a clean git tree; use --allow-dirty for debugging")
    tasks = config.get("tasks", [])
    if not tasks and config.get("task_manifest"):
        import yaml
        tasks = yaml.safe_load(Path(config["task_manifest"]).read_text()).get("tasks", [])
    if not tasks: raise ValueError("task manifest contains no tasks")
    for task in tasks: validate_graph(task["graph_file"])
    return tasks


def run_experiment(config, mode, selected="all", resume=False, rerun_failed=False,
                   dry_run=False, allow_dirty=False, models_path="configs/models.yaml"):
    tasks = validate_experiment(config, allow_dirty)
    if selected != "all": tasks = [t for t in tasks if t["task_id"] == selected]
    if not tasks: raise ValueError(f"unknown task {selected!r}")
    if dry_run:
        for task in tasks:
            for fault in task.get("faults", []): make_injector(fault)
        output = Path(config["experiment"]["output_dir"])
        if not output.parent.exists():
            raise ValueError(f"logging parent does not exist: {output.parent}")
        if config["environment"]["backend"] != "fake":
            providers = load_model_config(models_path)
            for role in (config["executor"]["provider"], config["guard"]["provider"]):
                if role not in providers: raise ValueError(f"unknown model provider {role}")
                provider = providers[role]
                if not provider.base_url or not provider.model or not os.getenv(provider.api_key_env):
                    raise ValueError(f"model provider {role} is not configured")
            if importlib.util.find_spec("desktop_env") is None:
                raise ValueError("OSWorld is not installed")
        return {"status": "dry_run_ready", "tasks": [t["task_id"] for t in tasks],
                "backend": config["environment"]["backend"], "mode": mode}

    name = config["experiment"]["name"]
    run_id = f"{name}-{mode}"
    run_logger = RunLogger(config["experiment"]["output_dir"], run_id, config,
        {"mode": mode, "seed": config["experiment"]["seed"],
         "environment_provider": config["environment"]["provider"],
         "executor_provider": config["executor"]["provider"],
         "executor_model": config["executor"].get("model"),
         "guard_provider": config["guard"]["provider"],
         "guard_model": config["guard"].get("model"),
         "benchmark_version": config["environment"].get("benchmark_version"),
         "task_manifest_hash": digest(tasks),
         "task_graph_hashes": {t["task_id"]: digest(validate_graph(t["graph_file"])) for t in tasks},
         "prompt_versions": {"phase2b": 1}})
    results = []
    for task in tasks:
        episodes = [("clean", None)] + [(f["fault_id"], f) for f in task.get("faults", [])
                                         if config["faults"].get("enabled", True)]
        for fault_id, fault in episodes:
            episode_id = f"{task['task_id']}--{mode}--{fault_id}"
            result_path = run_logger.episodes / episode_id / "result.json"
            if resume and result_path.exists():
                previous = json.loads(result_path.read_text())
                if previous.get("success") or not rerun_failed: continue
            raw_graph = validate_graph(task["graph_file"])
            state = load_manual_task(task["graph_file"])
            history = ActionHistory(config["runtime"]["history_window"])
            if config["executor"]["provider"] == "mock":
                executor_client = MockModelClient(_executor_policy(task, mode))
            else: executor_client = _real_client(config["executor"]["provider"], models_path)
            bounds = ActionBounds(config["environment"].get("screen_width", 1920),
                                  config["environment"].get("screen_height", 1080))
            executor = MLLMExecutor(executor_client, task["instruction"], history, bounds,
                                    config["runtime"]["max_executor_parse_retries"])
            if config["guard"]["provider"] == "mock":
                guard_client = MockModelClient(_guard_policy)
            else: guard_client = _real_client(config["guard"]["provider"], models_path)
            mllm = MLLMBackend(guard_client, history, config["runtime"]["max_guard_parse_retries"])
            guard = StateGuard(HybridBackend(RuleBackend(), mllm))
            runtime_task = {k: v for k, v in task.items() if k != "faults"}
            episode_logger = run_logger.episode(episode_id, runtime_task, raw_graph, fault)
            if config["environment"]["backend"] == "fake":
                backend = FakeOSWorldBackend(str(episode_logger.dir / "screenshots"))
            else:
                from integrations.osworld.adapter import DesktopEnvBackend
                backend = DesktopEnvBackend(provider=config["environment"]["provider"],
                                            headless=config["environment"]["headless"])
            env = OSWorldAdapter(backend, (bounds.width, bounds.height))
            runtime = config["runtime"]
            runner = EpisodeRunner(executor, guard, runtime["max_total_steps"],
                runtime["max_repair_cycles_per_fault"],
                runtime["max_unknown_verification_cycles"], mode, history)
            result = runner.run(env, state, runtime_task, task["task_id"], make_injector(fault), episode_logger)
            result.metrics = episode_metrics(result, fault or {}, DependencyGraph.from_state(state))
            episode_logger.finish(result)
            env.close(); results.append(result)
    summary_path = run_logger.dir / "summary.json"
    if resume and not results and summary_path.exists():
        return json.loads(summary_path.read_text())
    return run_logger.summarize(results)
