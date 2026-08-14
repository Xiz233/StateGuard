from __future__ import annotations

import csv
import hashlib
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml


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

    def episode(self, episode_id, task, graph, fault):
        return EpisodeLogger(self.episodes / episode_id, task, graph, fault)

    def summarize(self, results):
        rows = [r.to_dict() for r in results]
        validity_fields = (
            "fault_injected_step", "failure_exposed_step", "guard_first_detection_step",
            "guard_detection_delay", "early_detection", "first_root_prediction",
            "eventual_root_prediction", "first_root_accuracy", "eventual_root_accuracy",
            "repair_cycle_count", "repair_action_count", "preservable_nodes",
            "actually_preserved_nodes", "reexecuted_preserved_nodes",
            "state_preservation_rate", "strict_progress_preservation_rate",
            "guard_intervention_count", "certified_clean", "false_intervention_episode",
            "false_intervention_event_count")
        summary = {"episodes": len(rows),
                   "task_success_rate": sum(r["success"] for r in rows) / len(rows) if rows else 0,
                   "recovery_success_rate": sum(r["success"] and bool(r["fault_events"]) for r in rows)
                                            / max(1, sum(bool(r["fault_events"]) for r in rows)),
                   "total_steps": sum(r["total_steps"] for r in rows),
                   "model_calls": sum(r["executor_calls"] + r["guard_calls"] for r in rows),
                   "tokens": sum(r["executor_tokens"] + r["guard_tokens"] for r in rows),
                   "latency": sum(r["executor_latency"] + r["guard_latency"] for r in rows)}
        fault_rows = [r for r in rows if r["fault_events"]]
        clean_rows = [r for r in rows if not r["fault_events"]]
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
            "guard_intervention_count": sum(r["guard_intervention_count"] for r in rows),
            "episode_validity": [{"status": r["status"],
                                  **{key: r[key] for key in validity_fields}} for r in rows],
        })
        self.write(self.dir / "summary.json", summary)
        if rows:
            flat = [{k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                     for k, v in r.items()} for r in rows]
            with (self.dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, flat[0]); writer.writeheader(); writer.writerows(flat)
        return summary


class EpisodeLogger:
    def __init__(self, directory, task, graph, fault):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "screenshots").mkdir(exist_ok=True)
        RunLogger.write(self.dir / "task.json", task)
        RunLogger.write(self.dir / "task_graph.json", graph)
        RunLogger.write(self.dir / "fault_spec.json", fault or {})

    def append(self, name, value):
        with (self.dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, default=str) + "\n")

    def log_step(self, step, state, proposal, fault, exposure, executed, execution_phase,
                 repair_cycle_id, before, after, guard, repair, interventions):
        row = {"step": step, "task_state_before": state,
               "executor_proposal": proposal.to_dict(),
               "injected_fault": fault.to_dict() if fault else None,
               "failure_exposure": exposure.to_dict() if exposure else None,
               "executed_action": executed,
               "execution_phase": execution_phase,
               "repair_cycle_id": repair_cycle_id,
               "observation_before": before.to_dict(), "observation_after": after.to_dict(),
               "guard_result": guard.to_dict() if guard else None,
               "state_updates": guard.state_updates if guard else [],
               "repair_context": repair.to_dict() if hasattr(repair, "to_dict") else repair,
               "interventions": [event.to_dict() for event in interventions]}
        self.append("trajectory.jsonl", row)
        self.append("executor_events.jsonl", {"step": step, "proposal": proposal.to_dict()})
        if guard: self.append("guard_events.jsonl", {"step": step, **guard.to_dict()})
        if guard and guard.repair:
            self.append("repair_events.jsonl", {"step": step, "repair": guard.repair.to_dict()})

    def finish(self, result):
        RunLogger.write(self.dir / "model_usage.json", {
            k: getattr(result, k) for k in ("executor_calls", "guard_calls", "executor_tokens",
                                            "guard_tokens", "executor_latency", "guard_latency")})
        RunLogger.write(self.dir / "result.json", result.to_dict())
