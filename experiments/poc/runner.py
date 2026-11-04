from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

from stateguard.compiler.manual_loader import load_manual_task
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.executor.mllm_executor import MLLMExecutor
from stateguard.executor.parser import ActionBounds
from stateguard.guard.backends import HybridBackend, MLLMBackend, RuleBackend
from stateguard.guard.state_guard import StateGuard
from stateguard.models import create_model_client, load_model_config
from stateguard.models.mock import MockModelClient
from stateguard.planning import AutoDAGError, AutoDAGGenerator
from stateguard.planning.runtime_replanner import MLLMPlanPatchProvider, RuntimeReplanner
from stateguard.runtime.adaptive_verification import (
    AdaptiveVerificationConfig, AdaptiveVerificationController,
)
from stateguard.runtime.checkpoint_policy import CheckpointPolicy
from stateguard.runtime.episode_runner import EpisodeRunner
from stateguard.runtime.history import ActionHistory
from stateguard.runtime.verification_debt import VerificationDebtConfig
from stateguard.verification.grounder import MLLMGroundingProvider, VerificationGrounder
from stateguard.verification.registry import default_registry
from stateguard.verification.result import EvidenceResult
from stateguard.training_logging import RecordingModelClient
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter

from .faults import make_injector
from .logging import RunLogger, digest, git_metadata
from .metrics import episode_metrics


NATURAL_DESIGN = "natural_failure"
CONTROLLED_FAULT_DESIGN = "controlled_fault_diagnostic"


def _experiment_design(config) -> str:
    return config.get("experiment", {}).get("design", CONTROLLED_FAULT_DESIGN)


def _load_task_manifest(path, natural=False):
    import yaml
    manifest_path = Path(path)
    value = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if value.get("source_manifest"):
        source_path = Path(value["source_manifest"])
        if not source_path.is_absolute():
            source_path = manifest_path.parent.parent.parent / source_path
        source = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        selected = set(value.get("task_ids", ()))
        tasks = [task for task in source.get("tasks", [])
                 if not selected or task.get("task_id") in selected]
    else:
        tasks = value.get("tasks", [])
    if natural:
        return [{key: item for key, item in task.items() if key != "faults"}
                for task in tasks]
    return tasks


def _select_tasks(tasks, selected):
    if selected == "all":
        return tasks
    requested = {value.strip() for value in str(selected).split(",") if value.strip()}
    found = [task for task in tasks if task["task_id"] in requested]
    missing = requested - {task["task_id"] for task in found}
    if missing:
        raise ValueError(f"unknown task(s) {sorted(missing)}")
    return found


def _natural_repetitions(config):
    experiment = config.get("experiment", {})
    base_seed = int(experiment.get("seed", 0))
    repetitions = experiment.get("repetitions", 1)
    if isinstance(repetitions, int):
        if repetitions < 1:
            raise ValueError("experiment.repetitions must be positive")
        return tuple(base_seed + index for index in range(repetitions))
    values = tuple(int(value) for value in repetitions)
    if not values:
        raise ValueError("experiment.repetitions cannot be empty")
    return values


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
    if "candidate_states" in payload:
        state = payload["observation_after"].get("structured_state") or {}
        values = {}
        for candidate in payload["candidate_states"]:
            node_id = candidate["node_id"]
            expected = candidate.get("expected_state", "")
            untrusted = (("target" in expected and state.get("target") == "bad") or
                         ("value" in expected and state.get("value") == "bad"))
            values[node_id] = "NO" if untrusted else "YES"
        return {"trust_judgements": values}
    subgoal = payload["proposal"]["subgoal_id"]
    state = payload["after"].get("structured_state") or {}
    graph_nodes = payload["task_dag"]["nodes"]
    if state.get("target") == "bad" and subgoal in {"S2", "S4"}:
        root = "S2" if "S4" in graph_nodes else "S1"
        return {"judgement": "contradicted", "progress_updates": [], "fault_root": root,
                "fault_type": "wrong_target", "verification_target": None,
                "reason": "The value is in the wrong target; the earliest invalid state is S1."}
    return {"judgement": "verified", "progress_updates": [{"node_id": subgoal,
            "status": "verified", "evidence": f"Visible state supports {subgoal}."}],
            "fault_root": None, "fault_type": None, "verification_target": None,
            "reason": "Visible transition is consistent."}


def _mock_dag_policy(messages, images, schema):
    return {"nodes": [
        {"node_id": "S1", "description": "reach the target application state",
         "dependencies": [],
         "expected_result_semantic": "the target application state is reachable",
         "evidence_mode": "visual", "required": True},
        {"node_id": "S2", "description": "the requested task result is persisted",
         "dependencies": ["S1"],
         "expected_result_semantic": "the task result exists and is persisted",
         "evidence_mode": "persistence", "required": True},
    ]}


def _real_client(provider, models_path):
    return create_model_client(load_model_config(models_path)[provider])


def _git_commit(path):
    if not path:
        return None
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _osworld_available(root=None):
    if importlib.util.find_spec("desktop_env") is not None:
        return True
    return bool(root and (Path(root) / "desktop_env").is_dir())


def validate_graph(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    approval = raw.get("graph", {})
    if not approval.get("approved") or not approval.get("approved_by") or not approval.get("approved_at"):
        raise ValueError(f"manual DAG is not approved: {path}")
    load_manual_task(path)
    return raw


def _archive_episode_attempt(episode_dir: Path, run_dir: Path) -> Path | None:
    """Preserve a failed/partial attempt before reusing its episode id."""
    if not episode_dir.exists() or not any(episode_dir.iterdir()):
        return None
    root = run_dir / "attempts" / episode_dir.name
    root.mkdir(parents=True, exist_ok=True)
    index = 1
    while (root / f"attempt_{index:03d}").exists():
        index += 1
    destination = root / f"attempt_{index:03d}"
    shutil.move(str(episode_dir), destination)
    return destination


def _load_episode_result(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validate_experiment(config, allow_dirty=False):
    backend = config["environment"]["backend"]
    if backend != "fake" and git_metadata()["dirty_working_tree"] and not allow_dirty:
        raise ValueError("formal experiment requires a clean git tree; use --allow-dirty for debugging")
    natural = _experiment_design(config) == NATURAL_DESIGN
    tasks = config.get("tasks", [])
    if not tasks and config.get("task_manifest"):
        tasks = _load_task_manifest(config["task_manifest"], natural=natural)
    if not tasks: raise ValueError("task manifest contains no tasks")
    source = config.get("task_graph", {}).get("source", "manual")
    if source != "auto":
        for task in tasks: validate_graph(task["graph_file"])
    return tasks


def run_experiment(config, mode, selected="all", resume=False, rerun_failed=False,
                   dry_run=False, allow_dirty=False, models_path="configs/models.yaml",
                   scenario="all"):
    design = _experiment_design(config)
    natural = design == NATURAL_DESIGN
    tasks = _select_tasks(validate_experiment(config, allow_dirty), selected)
    fault_config = config.get("faults", {})
    enabled_faults = [
        fault
        for task in tasks
        for fault in task.get("faults", [])
        if not natural and fault_config.get("enabled", True)
    ]
    available_scenarios = ({"natural"} if natural else
                           {"clean", *(fault["fault_id"] for fault in enabled_faults)})
    if natural and scenario == "all":
        scenario = "natural"
    if scenario != "all" and scenario not in available_scenarios:
        raise ValueError(f"unknown scenario {scenario!r} for selected task(s)")
    if dry_run:
        if not natural:
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
            if not _osworld_available(config["environment"].get("root")):
                raise ValueError("OSWorld is not installed")
        return {"status": "dry_run_ready", "tasks": [t["task_id"] for t in tasks],
                "backend": config["environment"]["backend"], "mode": mode,
                "scenario": scenario, "design": design,
                "episodes": (len(tasks) * len(_natural_repetitions(config))
                             if natural else len(tasks) + len(enabled_faults))}

    providers = (load_model_config(models_path)
                 if config["environment"]["backend"] != "fake" else {})
    executor_provider = providers.get(config["executor"]["provider"])
    guard_provider = providers.get(config["guard"]["provider"])
    dag_source = config.get("task_graph", {}).get("source", "manual")
    verification_policy = config.get("verification", {}).get("policy", "dense")
    guidance = config.get("execution", {}).get("guidance", "dense")
    repeated_action_threshold = config.get("verification", {}).get(
        "repeated_action_threshold", 3)
    max_actions_per_subgoal = config.get("verification", {}).get(
        "max_actions_per_subgoal", 10)
    high_risk_interval = config.get("verification", {}).get("hybrid", {}).get(
        "high_risk_interval", 2)
    medium_risk_interval = config.get("verification", {}).get("hybrid", {}).get(
        "medium_risk_interval", 5)
    checkpoint_cooldown = config.get("verification", {}).get("hybrid", {}).get(
        "checkpoint_cooldown", 2)
    unchanged_observation_threshold = config.get("verification", {}).get(
        "unchanged_observation_threshold", 3)
    name = config["experiment"]["name"]
    run_id = f"{name}-{mode}"
    run_logger = RunLogger(config["experiment"]["output_dir"], run_id, config,
        {"mode": mode, "seed": config["experiment"]["seed"],
         "environment_provider": config["environment"]["provider"],
         "executor_provider": config["executor"]["provider"],
         "executor_model": executor_provider.model if executor_provider else "mock",
         "guard_provider": config["guard"]["provider"],
         "guard_model": guard_provider.model if guard_provider else "mock",
         "benchmark_version": config["environment"].get("benchmark_version"),
         "osworld_git_commit": _git_commit(config["environment"].get("root")),
         "task_manifest_hash": digest(tasks),
         "experiment_design": design,
         **({"fault_manifest_hash": digest(enabled_faults)} if not natural else {}),
         "task_graph_hashes": ({t["task_id"]: digest(validate_graph(t["graph_file"])) for t in tasks}
                               if dag_source != "auto" else {}),
         "dag_source": dag_source, "verification_policy": verification_policy,
         "execution_guidance": guidance, "prompt_versions": {"phase2b": 1}})
    results = []
    for task in tasks:
        episodes = ([(f"seed-{seed}", None, seed)
                     for seed in _natural_repetitions(config)] if natural else
                    [("clean", None, config["experiment"]["seed"])]
                    + [(f["fault_id"], f, config["experiment"]["seed"])
                       for f in task.get("faults", [])
                       if fault_config.get("enabled", True)])
        if scenario != "all":
            episodes = [episode for episode in episodes
                        if scenario == "natural" or episode[0] == scenario]
        for condition_id, fault, run_seed in episodes:
            mode_id = mode.replace("_", "-") if natural else mode
            episode_id = f"{task['task_id']}--{mode_id}--{condition_id}"
            result_path = run_logger.episodes / episode_id / "result.json"
            if resume and result_path.exists():
                previous = _load_episode_result(result_path)
                if previous is not None and (
                        previous.get("success") or not rerun_failed):
                    continue
            if resume:
                _archive_episode_attempt(result_path.parent, run_logger.dir)
            raw_graph = None if dag_source == "auto" else validate_graph(task["graph_file"])
            state = load_manual_task(task["graph_file"])
            history = ActionHistory(config["runtime"]["history_window"])
            runtime_task = {k: v for k, v in task.items() if k != "faults"}
            runtime_task.update({
                "experiment_design": design,
                "system_mode": mode,
                "run_seed": run_seed,
                "repetition_id": condition_id,
            })
            if fault is None and not natural:
                runtime_task["certified_clean"] = True
            logging_config = config.get("evaluation", {})
            episode_logger = run_logger.episode(
                episode_id, runtime_task, raw_graph, fault,
                training_ready=logging_config.get("training_ready_logging", True),
                save_model_responses=logging_config.get("save_model_responses", False))
            if config["executor"]["provider"] == "mock":
                executor_client = MockModelClient(_executor_policy(task, mode))
            else: executor_client = _real_client(config["executor"]["provider"], models_path)
            if episode_logger.training is not None:
                executor_client = RecordingModelClient(
                    executor_client, episode_logger.training, "executor")
            bounds = ActionBounds(config["environment"].get("screen_width", 1920),
                                  config["environment"].get("screen_height", 1080))
            executor = MLLMExecutor(executor_client, task["instruction"], history, bounds,
                                    config["runtime"].get(
                                        "max_parse_retry_per_call",
                                        config["runtime"]["max_executor_parse_retries"]),
                                    coordinate_scale=config["environment"].get(
                                        "executor_coordinate_scale"),
                                    require_verified_deps=config.get("executor", {}).get(
                                        "require_verified_deps", True),
                                    guidance=guidance)
            if config["guard"]["provider"] == "mock":
                guard_base_client = MockModelClient(_guard_policy)
            else:
                guard_base_client = _real_client(
                    config["guard"]["provider"], models_path)
            guard_client = (RecordingModelClient(
                guard_base_client, episode_logger.training, "guard")
                if episode_logger.training is not None else guard_base_client)
            runtime = config["runtime"]
            mllm = MLLMBackend(
                guard_client, history,
                runtime.get("max_parse_retry_per_call",
                            runtime["max_guard_parse_retries"]),
                max_total_calls=runtime.get("max_total_guard_calls"))
            guard = StateGuard(HybridBackend(RuleBackend(), mllm))
            adaptive = config.get("adaptive_verification", {})
            debt_config = config.get("verification_debt", adaptive.get("debt", {}))
            replanning = config.get("runtime_replanning", {})
            checkpoint_config = config.get("checkpoint", {})
            adaptive_controller = runtime_replanner = None
            if adaptive.get("enabled", False):
                registry = default_registry(
                    lambda contract, _observation: EvidenceResult.unknown(
                        "visual_mllm", sources=contract.sources,
                        reason="visual evidence is evaluated by StateGuard"))
                grounder = VerificationGrounder(
                    None if config["guard"]["provider"] == "mock"
                    else MLLMGroundingProvider(RecordingModelClient(
                        guard_base_client, episode_logger.training, "grounder")
                        if episode_logger.training is not None else guard_base_client))
                adaptive_controller = AdaptiveVerificationController(
                    grounder, registry,
                    AdaptiveVerificationConfig(
                        max_grounding_attempts=adaptive.get("max_grounding_attempts", 2),
                        max_reground_per_node=runtime.get(
                            "max_reground_per_node",
                            adaptive.get("max_reground_per_node", 2)),
                        ground_on_context_shift=adaptive.get(
                            "ground_on_context_shift", True),
                        debt_enabled=debt_config.get("enabled", True),
                        debt=VerificationDebtConfig(
                            soft_threshold=debt_config.get("soft_threshold", 2),
                            strategy_switch_threshold=debt_config.get(
                                "reground_threshold",
                                debt_config.get("strategy_switch_threshold", 3)),
                            hard_threshold=debt_config.get("hard_threshold", 5))))
                if replanning.get("enabled", True):
                    runtime_replanner = RuntimeReplanner(
                        MLLMPlanPatchProvider(
                            RecordingModelClient(
                                guard_base_client, episode_logger.training, "replanner")
                            if episode_logger.training is not None else guard_base_client,
                            replanning.get("max_patch_attempts", 2)))
            environment = config["environment"]
            if config["environment"]["backend"] == "fake":
                backend = FakeOSWorldBackend(str(episode_logger.dir / "screenshots"))
            else:
                from integrations.osworld.adapter import DesktopEnvBackend
                backend = DesktopEnvBackend(
                    provider=environment["provider"], headless=environment["headless"],
                    osworld_root=environment.get("root"),
                    path_to_vm=environment.get("vm_path"),
                    cache_dir=environment.get("cache_dir", "cache"),
                    require_a11y_tree=environment.get("require_a11y_tree", False),
                    enable_proxy=environment.get("enable_proxy", False),
                    client_password=environment.get("client_password", "password"),
                )
            env = OSWorldAdapter(
                backend,
                (bounds.width, bounds.height),
                reset_ready_timeout_seconds=environment.get("reset_ready_timeout_seconds", 0),
                reset_poll_seconds=environment.get("reset_poll_seconds", 2),
                reset_settle_seconds=environment.get("reset_settle_seconds", 0),
            )
            runner = EpisodeRunner(executor, guard, runtime["max_total_steps"],
                config.get("repair", {}).get(
                    "max_cycles", runtime["max_repair_cycles_per_fault"]),
                runtime["max_unknown_verification_cycles"], mode, history,
                max_repair_actions_per_cycle=config.get("repair", {}).get(
                    "max_actions_per_cycle", 20),
                trace_max_entries=config.get("trace", {}).get("max_entries", 200),
                trace_keep_recent_images=config.get("trace", {}).get(
                    "keep_recent_images", 10),
                unchanged_observation_threshold=unchanged_observation_threshold,
                adaptive_controller=adaptive_controller,
                runtime_replanner=runtime_replanner,
                max_replans_per_node=replanning.get(
                    "max_replans_per_node", adaptive.get("max_replans_per_node", 2)),
                max_replans_per_episode=replanning.get(
                    "max_replans_per_episode", adaptive.get("max_replans_per_episode", 5)),
                max_consecutive_unknown=runtime.get("max_consecutive_unknown", 8),
                suppress_repeated_completion_claims=checkpoint_config.get(
                    "suppress_repeated_completion_claims", True),
                verification_policy=verification_policy,
                checkpoint_policy=CheckpointPolicy(
                    policy=verification_policy,
                    repeated_action_threshold=repeated_action_threshold,
                    same_subgoal_step_threshold=max_actions_per_subgoal,
                    high_risk_interval=high_risk_interval,
                    medium_risk_interval=medium_risk_interval,
                    checkpoint_cooldown=checkpoint_cooldown))
            dag_holder: dict = {}
            run_kwargs: dict = {}
            if dag_source == "auto":
                def dag_provider(obs):
                    gen = AutoDAGGenerator(
                        MockModelClient(_mock_dag_policy)
                        if config["guard"]["provider"] == "mock"
                        else _real_client(config["guard"]["provider"], models_path),
                        max_attempts=2)
                    res = gen.generate(task["instruction"], obs)
                    dag_holder.update({"gen": gen, "res": res})
                    episode_logger.save_dag_artifacts(res)
                    if not res.valid:
                        raise AutoDAGError(res.error or "auto-DAG generation failed")
                    return compile_from_spec({"nodes": res.nodes})
                run_kwargs = {"dag_provider": dag_provider}
            injector = make_injector(fault) if fault is not None else None
            try:
                result = runner.run(env, state, runtime_task, task["task_id"], injector,
                                    episode_logger, **run_kwargs)
                result.dag_source = dag_source
                if dag_source == "auto" and dag_holder.get("res"):
                    res, gen = dag_holder["res"], dag_holder["gen"]
                    result.dag_generation_valid = res.valid
                    result.dag_generation_attempts = res.attempts
                    result.dag_node_count = len(res.nodes) if res.valid else 0
                    result.dag_edge_count = (sum(len(n["dependencies"]) for n in res.nodes)
                                             if res.valid else 0)
                    result.dag_generation_calls = gen.calls
                    result.dag_generation_tokens = gen.tokens
                    result.dag_generation_latency = gen.latency
                result.metrics = {
                    **episode_metrics(result, fault or {},
                                      DependencyGraph.from_state(result.task_state)),
                    "experiment_design": design,
                    "task_id": task["task_id"],
                    "system_mode": mode,
                    "run_seed": run_seed,
                    "repetition_id": condition_id,
                    "natural_execution": natural,
                    **({
                        "fault_condition": bool(fault),
                        "fault_injected": bool(result.fault_events),
                        "fault_effect_observed": (
                            bool(result.root_predictions)
                            or result.fault_reexecution_observed
                            if mode == "stateguard" and fault else
                            bool(result.fault_events)),
                    } if not natural else {}),
                }
                episode_logger.finish(result)
                results.append(result)
            finally:
                env.close()
    summary_path = run_logger.dir / "summary.json"
    if resume and not results and summary_path.exists():
        stored = _stored_episode_results(run_logger.episodes)
        return run_logger.summarize(stored) if stored else json.loads(
            summary_path.read_text())
    if resume:
        return run_logger.summarize(_stored_episode_results(run_logger.episodes))
    return run_logger.summarize(results)


def _stored_episode_results(episodes_dir: Path) -> list[dict]:
    results = []
    for path in sorted(episodes_dir.glob("*/result.json")):
        value = _load_episode_result(path)
        if value is not None:
            results.append(value)
    return results
