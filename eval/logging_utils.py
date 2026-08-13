"""Per-episode JSON logging (指引.txt §28):

run/<episode>/
    task.json               task spec
    task_state_initial.json compiled state
    task_state_final.json   final state
    trajectory.jsonl        per-step: proposal/state_before/observations/guard_result
    guard_events.jsonl      guard judgements
    repair_events.jsonl     repair requests
    metrics.json            per-episode metrics
"""

from __future__ import annotations

import json
from pathlib import Path


class EpisodeLogger:
    def __init__(self, run_dir: str, episode: str):
        self.dir = Path(run_dir) / episode
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, obj) -> None:
        with open(self.dir / name, "w") as f:
            json.dump(obj, f, indent=2, default=str)

    def append(self, name: str, row: dict) -> None:
        with open(self.dir / name, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")

    def log_task(self, spec: dict, state) -> None:
        self.write("task.json", spec)
        self.write("task_state_initial.json", state.serialize())

    def log_step(self, step: int, proposal, state_before, obs_before, obs_after,
                 guard_result, state_updates) -> None:
        self.append("trajectory.jsonl", {
            "step": step,
            "proposal": proposal.to_dict() if proposal else None,
            "state_before": state_before,
            "observation_before": obs_before.to_dict(),
            "observation_after": obs_after.to_dict(),
            "guard_result": guard_result.to_dict(),
            "state_updates": state_updates,
        })

    def log_guard_event(self, step: int, result) -> None:
        self.append("guard_events.jsonl", {
            "step": step,
            "judgement": result.judgement,
            "fault_root": result.fault_root,
            "fault_type": result.fault_type,
            "verification_target": result.verification_target,
            "repair": result.repair.to_dict() if result.repair else None,
        })

    def log_repair(self, step: int, repair) -> None:
        self.append("repair_events.jsonl", {"step": step, "repair": repair.to_dict()})

    def finish(self, state, metrics: dict) -> None:
        self.write("task_state_final.json", state.serialize())
        self.write("metrics.json", metrics)
