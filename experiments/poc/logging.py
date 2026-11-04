from __future__ import annotations

import csv
import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from stateguard.training_logging import TrainingReadyLogger


def digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def git_metadata():
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
    return {"git_commit": git("rev-parse", "HEAD"),
            "dirty_working_tree": bool(git("status", "--porcelain"))}


class RunLogger:
    def __init__(self, output_dir, run_id, config, metadata):
        self.dir = Path(output_dir) / run_id
        self.episodes = self.dir / "episodes"
        self.episodes.mkdir(parents=True, exist_ok=True)
        full_meta = {**git_metadata(), "timestamp": datetime.now(timezone.utc).isoformat(),
                     "hostname": socket.gethostname(), "config_hash": digest(config), **metadata}
        self.write(self.dir / "run_metadata.json", full_meta)
        (self.dir / "config_resolved.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    @staticmethod
    def write(path, value):
        Path(path).write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def write_results_csv(path, rows):
        """Write mixed-version episode rows without assuming identical schemas."""
        if not rows:
            return
        flat = [{key: json.dumps(value, sort_keys=True)
                 if isinstance(value, (dict, list)) else value
                 for key, value in row.items()} for row in rows]
        fieldnames = list(dict.fromkeys(
            key for row in flat for key in row
        ))
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat)

    def episode(self, episode_id, task, graph, diagnostic_spec=None,
                training_ready=True, save_model_responses=True):
        return EpisodeLogger(
            self.episodes / episode_id, task, graph, diagnostic_spec,
            training_ready=training_ready,
            save_model_responses=save_model_responses)

    def summarize(self, results):
        rows = [r if isinstance(r, dict) else r.to_dict() for r in results]
        if rows and all((row.get("metrics") or {}).get("natural_execution")
                        for row in rows):
            return self._summarize_natural(rows)
        validity_fields = (
            "fault_injected_step", "failure_exposed_step", "guard_first_detection_step",
            "guard_detection_delay", "early_detection", "first_root_prediction",
            "eventual_root_prediction", "first_root_accuracy", "eventual_root_accuracy",
            "repair_cycle_count", "repair_action_count", "preservable_nodes",
            "repair_budget_exhaustions", "suspicious_checkpoint_count",
            "trace_entry_count",
            "actually_preserved_nodes", "reexecuted_preserved_nodes",
            "state_preservation_rate", "strict_progress_preservation_rate",
            "guard_intervention_count", "certified_clean", "false_intervention_episode",
            "false_intervention_event_count", "fault_reexecution_observed",
            "dag_source", "dag_node_count", "dag_edge_count", "dag_generation_valid",
            "dag_generation_attempts", "frontier_violation_count",
            "frontier_recovery_count", "checkpoint_count",
            "checkpoint_reasons", "checkpoint_kinds", "premature_finish_count",
            "verification_calls", "unknown_checkpoint_count", "contradiction_count",
            "plan_revision_count", "local_replan_count", "local_replan_success_count",
            "contracts_generated", "contract_revision_count",
            "contract_validation_failure_count", "semantic_weakening_rejected",
            "contract_stale_count", "nodes_unverifiable",
            "verification_debt_trigger_count", "evidence_source_switch_count",
            "executor_overclaim_count",
            "guard_parse_fail_open_count", "guard_strategy_normalization_count",
            "guard_progress_update_drop_count", "replanner_fallback_count",
            "actions_per_subgoal", "steps_between_checkpoints")
        fault_rows = [r for r in rows if r.get("metrics", {}).get("fault_condition")]
        clean_rows = [r for r in rows if not r.get("metrics", {}).get("fault_condition")]
        summary = {"episodes": len(rows),
                   "task_success_rate": sum(r["success"] for r in rows) / len(rows) if rows else 0,
                   "recovery_success_rate": (sum(r["success"] for r in fault_rows)
                                             / len(fault_rows) if fault_rows else 0),
                   "fault_injection_validity_rate": (
                       sum(bool(r["metrics"].get("fault_effect_observed")) for r in fault_rows)
                       / len(fault_rows)
                       if fault_rows else 1.0),
                   "total_steps": sum(r["total_steps"] for r in rows),
                   "model_calls": sum(
                       r["executor_calls"] + r["guard_calls"] + r["grounder_calls"]
                       + r["replanner_calls"] for r in rows),
                   "tokens": sum(
                       r["executor_tokens"] + r["guard_tokens"] + r["grounder_tokens"]
                       + r["replanner_tokens"] for r in rows),
                   "latency": sum(
                       r["executor_latency"] + r["guard_latency"] + r["grounder_latency"]
                       + r["replanner_latency"] for r in rows)}
        summary.update({
            "first_root_accuracy": (sum(r["first_root_accuracy"] for r in fault_rows)
                                    / len(fault_rows) if fault_rows else 0),
            "eventual_root_accuracy": (sum(r["eventual_root_accuracy"] for r in fault_rows)
                                       / len(fault_rows) if fault_rows else 0),
            "affected_set_f1": (sum(r["metrics"].get("affected_set_f1", 0) for r in fault_rows)
                                / len(fault_rows) if fault_rows else 0),
            "state_preservation_rate": (sum(r["state_preservation_rate"] for r in fault_rows)
                                        / len(fault_rows) if fault_rows else 1),
            "strict_progress_preservation_rate": (
                sum(r["strict_progress_preservation_rate"] for r in fault_rows) / len(fault_rows)
                if fault_rows else 1),
            "false_intervention_rate": (
                sum(r["false_intervention_episode"] for r in clean_rows if r["certified_clean"])
                / max(1, sum(r["certified_clean"] for r in clean_rows))),
            "repair_radius": sum(r["metrics"].get("repair_radius", 0) for r in rows),
            "repair_cycle_count": sum(r["repair_cycle_count"] for r in rows),
            "repair_action_count": sum(r["repair_action_count"] for r in rows),
            "repair_budget_exhaustion_count": sum(
                len(r["repair_budget_exhaustions"]) for r in rows),
            "suspicious_checkpoint_count": sum(
                r["suspicious_checkpoint_count"] for r in rows),
            "trace_entry_count": sum(r["trace_entry_count"] for r in rows),
            "guard_intervention_count": sum(r["guard_intervention_count"] for r in rows),
            "verification_calls": sum(r["verification_calls"] for r in rows),
            "checkpoint_count": sum(r["checkpoint_count"] for r in rows),
            "unknown_checkpoint_count": sum(r["unknown_checkpoint_count"] for r in rows),
            "contradiction_count": sum(r["contradiction_count"] for r in rows),
            "premature_finish_count": sum(r["premature_finish_count"] for r in rows),
            "plan_revision_count": sum(r["plan_revision_count"] for r in rows),
            "local_replan_count": sum(r["local_replan_count"] for r in rows),
            "local_replan_success_count": sum(
                r["local_replan_success_count"] for r in rows),
            "contracts_generated": sum(r["contracts_generated"] for r in rows),
            "contract_revision_count": sum(r["contract_revision_count"] for r in rows),
            "contract_validation_failure_count": sum(
                r["contract_validation_failure_count"] for r in rows),
            "semantic_weakening_rejected": sum(
                r["semantic_weakening_rejected"] for r in rows),
            "contract_stale_count": sum(r["contract_stale_count"] for r in rows),
            "nodes_unverifiable": sum(r["nodes_unverifiable"] for r in rows),
            "verification_debt_trigger_count": sum(
                r["verification_debt_trigger_count"] for r in rows),
            "evidence_source_switch_count": sum(
                r["evidence_source_switch_count"] for r in rows),
            "executor_overclaim_count": sum(r["executor_overclaim_count"] for r in rows),
            "executor_finish_reconciliation_count": sum(
                r.get("executor_finish_reconciliation_count", 0) for r in rows),
            "guard_parse_fail_open_count": sum(
                r.get("guard_parse_fail_open_count", 0) for r in rows),
            "guard_strategy_normalization_count": sum(
                r.get("guard_strategy_normalization_count", 0) for r in rows),
            "guard_progress_update_drop_count": sum(
                r.get("guard_progress_update_drop_count", 0) for r in rows),
            "replanner_fallback_count": sum(
                r.get("replanner_fallback_count", 0) for r in rows),
            "frontier_violation_count": sum(r["frontier_violation_count"] for r in rows),
            "dag_generation_calls": sum(r["dag_generation_calls"] for r in rows),
            "dag_generation_tokens": sum(r["dag_generation_tokens"] for r in rows),
            "dag_generation_latency": sum(r["dag_generation_latency"] for r in rows),
            "episode_validity": [{"status": r["status"],
                                  **{key: r.get(key) for key in validity_fields}} for r in rows],
        })
        summary["grounding_success_rate"] = (
            summary["contracts_generated"]
            / max(1, summary["contracts_generated"]
                  + summary["contract_validation_failure_count"]))
        summary["contract_revision_success_rate"] = (
            summary["contract_revision_count"]
            / max(1, summary["contract_revision_count"]
                  + summary["contract_validation_failure_count"]))
        summary["local_replan_success_rate"] = (
            summary["local_replan_success_count"]
            / max(1, summary["local_replan_count"]))
        summary["goal_weakening_acceptance_rate"] = 0.0
        self.write(self.dir / "summary.json", summary)
        self.write_results_csv(self.dir / "results.csv", rows)
        return summary

    def _summarize_natural(self, rows):
        """Primary summary for natural execution; no injected-ground-truth metrics."""
        def total(key):
            return sum((row.get(key, 0) or 0) for row in rows)

        def verification_complete(row):
            nodes = (row.get("task_state") or {}).get("nodes", {})
            required = [node for node in nodes.values() if node.get("required", True)]
            return bool(required) and all(
                node.get("status") == "verified" and node.get("evidence")
                for node in required)

        summary = {
            "experiment_design": "natural_failure",
            "episodes": len(rows),
            "task_success_rate": total("success") / len(rows) if rows else 0,
            "verification_completeness_rate": (
                sum(verification_complete(row) for row in rows) / len(rows)
                if rows else 0),
            "status_counts": {
                status: sum(row.get("status") == status for row in rows)
                for status in sorted({row.get("status") for row in rows})
            },
            "total_steps": total("total_steps"),
            "model_calls": sum(
                total(key) for key in (
                    "executor_calls", "guard_calls", "grounder_calls", "replanner_calls")),
            "tokens": sum(
                total(key) for key in (
                    "executor_tokens", "guard_tokens", "grounder_tokens", "replanner_tokens")),
            "latency": sum(
                total(key) for key in (
                    "executor_latency", "guard_latency", "grounder_latency",
                    "replanner_latency")),
        }
        for key in (
            "executor_calls", "guard_calls", "grounder_calls", "replanner_calls",
            "verification_calls", "unknown_checkpoint_count", "contradiction_count",
            "premature_finish_count", "suspicious_checkpoint_count",
            "guard_intervention_count", "repair_cycle_count", "repair_action_count",
            "local_replan_count", "local_replan_success_count", "contracts_generated",
            "contract_revision_count", "verification_debt_trigger_count",
            "evidence_source_switch_count", "nodes_unverifiable",
            "frontier_violation_count", "frontier_recovery_count",
            "executor_finish_reconciliation_count",
        ):
            summary[key] = total(key)
        summary["unknown_rate"] = (
            summary["unknown_checkpoint_count"] / max(1, summary["verification_calls"]))
        summary["local_replan_success_rate"] = (
            summary["local_replan_success_count"]
            / max(1, summary["local_replan_count"]))
        self.write(self.dir / "summary.json", summary)
        self.write_results_csv(self.dir / "results.csv", rows)
        return summary


class EpisodeLogger:
    def __init__(self, directory, task, graph, diagnostic_spec=None,
                 training_ready=True, save_model_responses=True):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "screenshots").mkdir(exist_ok=True)
        RunLogger.write(self.dir / "task.json", task)
        RunLogger.write(self.dir / "task_graph.json", graph)
        if diagnostic_spec is not None:
            # Kept only for legacy controlled-fault diagnostics. Natural-failure
            # experiments intentionally have no artificial fault artifact.
            RunLogger.write(self.dir / "fault_spec.json", diagnostic_spec)
        self.training = (TrainingReadyLogger(
            self.dir, save_model_responses=save_model_responses)
            if training_ready else None)
        self._training_finished = False

    def append(self, name, value):
        with (self.dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, default=str) + "\n")

    def start_event(self, event_type, step, state_before=None, **payload):
        if self.training is None:
            return None
        return self.training.start_event(
            event_type, step, state_before=state_before, **payload)

    def finish_event(self, event_id, event_type, step, state_before, state_after,
                     status="completed", **payload):
        if self.training is None or event_id is None:
            return
        self.training.finish_event(
            event_id, event_type, step, state_before, state_after, status, **payload)

    def bind_event(self, event_id):
        if self.training is None:
            from contextlib import nullcontext
            return nullcontext()
        return self.training.bind_event(event_id)

    def record_observation(self, observation, role, producer_id):
        if self.training is None or observation is None:
            return None
        return self.training.register_artifact(
            observation.screenshot, role, producer_id)

    def record_intervention(self, step, intervention_type, **payload):
        if self.training is None:
            return None
        return self.training.record_intervention(step, intervention_type, **payload)

    def record_evaluator(self, result=None, error=None, event_id=None,
                         task_state=None):
        if self.training is not None:
            self.training.record_evaluator(
                result, error, event_id=event_id, task_state=task_state)

    def record_unknown(self, event_id, step, node_id, guard_result, evidence=None):
        if self.training is not None:
            return self.training.record_unknown(
                event_id, step, node_id, guard_result, evidence)

    def resolve_unknowns(self, node_id, resolution, step, evidence=None,
                         source="later_state"):
        if self.training is not None:
            self.training.resolve_unknowns(
                node_id, resolution, step, evidence, source)

    def close_unknowns(self, success, evaluator_event_id):
        if self.training is not None:
            self.training.close_unknowns(success, evaluator_event_id)

    def record_termination(self, status, error, step, task_state):
        if self.training is not None:
            self.training.record_termination(status, error, step, task_state)

    def _observation(self, observation, label, step):
        value = observation.to_dict()
        screenshot = observation.screenshot
        if isinstance(screenshot, bytes):
            path = self.dir / "screenshots" / f"step_{step:03d}_{label}.png"
            canonical = (self.dir / "artifacts"
                         / f"{hashlib.sha256(screenshot).hexdigest()}.png")
            if canonical.is_file():
                path.unlink(missing_ok=True)
                try:
                    os.link(canonical, path)
                except OSError:
                    path.write_bytes(screenshot)
            else:
                path.write_bytes(screenshot)
            value["screenshot"] = str(path)
        return value

    def log_step(self, step, state, proposal, fault, exposure, executed, execution_phase,
                 repair_cycle_id, repair_phase, before, after, guard, repair, interventions):
        row = {"step": step, "task_state_before": state,
               "executor_proposal": proposal.to_dict(),
               "injected_fault": fault.to_dict() if fault else None,
               "failure_exposure": exposure.to_dict() if exposure else None,
               "executed_action": executed,
               "execution_phase": execution_phase,
               "repair_phase": repair_phase,
               "repair_cycle_id": repair_cycle_id,
               "observation_before": self._observation(before, "before", step),
               "observation_after": self._observation(after, "after", step),
               "guard_result": guard.to_dict() if guard else None,
               "state_updates": guard.state_updates if guard else [],
               "repair_context": repair.to_dict() if hasattr(repair, "to_dict") else repair,
               "interventions": [event.to_dict() for event in interventions]}
        self.append("trajectory.jsonl", row)
        self.append("executor_events.jsonl", {"step": step, "proposal": proposal.to_dict()})
        if guard: self.append("guard_events.jsonl", {"step": step, **guard.to_dict()})
        if guard and guard.repair:
            self.append("repair_events.jsonl", {"step": step, "repair": guard.repair.to_dict()})
        for intervention in interventions:
            value = intervention.to_dict()
            self.record_intervention(
                step, value.get("intervention_type", "unknown"),
                decision=value, execution={"scheduled": True},
                immediate_result={"guard_judgement": getattr(guard, "judgement", None)},
                task_state=state)

    def save_dag_artifacts(self, dag_result):
        RunLogger.write(self.dir / "generated_dag.json", dag_result.to_dict())
        if dag_result.raw_responses:
            RunLogger.write(self.dir / "dag_generation_raw_response.json", dag_result.raw_responses)
        if dag_result.validation:
            RunLogger.write(self.dir / "dag_validation.json", dag_result.validation)
        if dag_result.valid:
            RunLogger.write(self.dir / "task_graph.json", {"nodes": dag_result.nodes})

    def finish(self, result):
        RunLogger.write(self.dir / "model_usage.json", {
            k: getattr(result, k) for k in ("executor_calls", "guard_calls", "executor_tokens",
                                            "guard_tokens", "executor_latency", "guard_latency",
                                            "grounder_calls", "grounder_tokens",
                                            "grounder_latency", "replanner_calls",
                                            "replanner_tokens", "replanner_latency",
                                            "guard_parse_fail_open_count",
                                            "guard_strategy_normalization_count",
                                            "guard_progress_update_drop_count",
                                            "replanner_fallback_count",
                                            "dag_generation_calls", "dag_generation_tokens",
                                            "dag_generation_latency", "verification_calls")})
        RunLogger.write(self.dir / "result.json", result.to_dict())
        if self.training is not None and not self._training_finished:
            self.training.close_interventions(
                result.status, result.success, result.environment_score)
            self._training_finished = True
