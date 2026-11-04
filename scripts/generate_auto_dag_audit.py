"""Offline Auto-DAG audit (planning/phase-12): generate a semantic DAG for each
of the 12 PoC tasks from the user instruction (manual DAG is used only as an
offline reference, never as input to the generator)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from stateguard.compiler.manual_loader import load_manual_task
from stateguard.models import create_model_client, load_model_config
from stateguard.planning import AutoDAGGenerator
from stateguard.runtime.checkpoint_policy import SparseCheckpointPolicy
from stateguard.runtime.episode_runner import EpisodeRunner

TASK_MANIFEST = "configs/poc/selected_tasks.yaml"
MODELS = "configs/models.yaml"
OUT = "/data/research/stateguard_runs/auto_dag_audit"


class DummyObservation:
    """Audit generation uses the instruction only (no VM screenshot)."""
    def __init__(self):
        self.screenshot = None


def main():
    tasks = yaml.safe_load(Path(TASK_MANIFEST).read_text())["tasks"]
    providers = load_model_config(MODELS)
    guard_cfg = providers["stateguard_api"]
    client = create_model_client(guard_cfg)
    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)

    report_lines = ["# Auto-DAG vs Manual DAG audit", ""]
    summary = []
    for task in tasks:
        tid = task["task_id"]
        gen = AutoDAGGenerator(client, max_attempts=2)
        res = gen.generate(task["instruction"], DummyObservation())
        manual = load_manual_task(task["graph_file"])
        manual_nodes = [n.to_dict() for n in manual.nodes.values()]
        entry_dir = out / tid
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "generated_dag.json").write_text(
            json.dumps(res.to_dict(), indent=2, default=str))
        (entry_dir / "task_instruction.txt").write_text(task["instruction"])
        (entry_dir / "manual_dag.json").write_text(
            json.dumps(manual_nodes, indent=2, default=str))
        status = "VALID" if res.valid else "INVALID"
        summary.append((tid[:8], status, res.attempts,
                        len(res.nodes) if res.valid else 0,
                        len(manual_nodes), res.error or "-"))
        report_lines.append(f"## {tid} [{status}]")
        report_lines.append(f"Instruction: {task['instruction']}")
        if res.valid:
            for n in res.nodes:
                report_lines.append(
                    f"  - {n['node_id']} ({n['evidence_mode']}): {n['description']}"
                    f"  <- {n['dependencies']}")
        else:
            report_lines.append(f"  ERROR: {res.error}")
        report_lines.append("")
        print(f"{tid[:8]} {status} auto={len(res.nodes) if res.valid else 0} "
              f"manual={len(manual_nodes)} {res.error or ''}")

    report_lines.append("## Summary")
    report_lines.append("| task | status | attempts | auto_nodes | manual_nodes | error |")
    report_lines.append("|---|---|---|---|---|---|")
    for row in summary:
        report_lines.append("| {} | {} | {} | {} | {} | {} |".format(*row))
    (out / "audit_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    print("audit written to", out)


if __name__ == "__main__":
    main()