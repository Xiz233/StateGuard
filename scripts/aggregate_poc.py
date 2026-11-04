from __future__ import annotations

import argparse
import json
from pathlib import Path


MODES = ("executor_only", "latest_retry", "stateguard")
METRICS = ("task_success_rate", "recovery_success_rate", "first_root_accuracy",
           "strict_progress_preservation_rate", "affected_set_f1",
           "false_intervention_rate", "repair_action_count", "total_steps",
           "fault_injection_validity_rate")


def load_summaries(root: Path, experiment: str) -> dict:
    summaries = {}
    for mode in MODES:
        path = root / f"{experiment}-{mode}" / "summary.json"
        if not path.is_file():
            raise ValueError(f"missing summary for {mode}: {path}")
        summaries[mode] = json.loads(path.read_text(encoding="utf-8"))
    return summaries


def decision(summaries: dict) -> tuple[str, list[str]]:
    guard, latest = summaries["stateguard"], summaries["latest_retry"]
    checks = {
        "Recovery SR improves over LatestRetry by >=10pp":
            guard["recovery_success_rate"] >= latest["recovery_success_rate"] + 0.10,
        "First Root Accuracy >=70%": guard["first_root_accuracy"] >= 0.70,
        "Strict Progress Preservation >=80%":
            guard["strict_progress_preservation_rate"] >= 0.80,
        "False Intervention <=15%": guard["false_intervention_rate"] <= 0.15,
        "All fault conditions injected": guard.get("fault_injection_validity_rate") == 1.0,
    }
    return ("GO" if all(checks.values()) else "NO-GO",
            [f"- [{'x' if passed else ' '}] {name}" for name, passed in checks.items()])


def main():
    parser = argparse.ArgumentParser(description="Aggregate the first 108-episode PoC")
    parser.add_argument("--runs", default="/data/research/stateguard_runs/poc_v1_108")
    parser.add_argument("--experiment", default="osworld_stateguard_poc")
    parser.add_argument("--output", default="artifacts/poc_v1_report.md")
    args = parser.parse_args()
    summaries = load_summaries(Path(args.runs), args.experiment)
    verdict, checks = decision(summaries)
    lines = ["# StateGuard first-round PoC", "", f"**Decision: {verdict}**", "",
             "| Metric | ExecutorOnly | LatestRetry | StateGuard |",
             "|---|---:|---:|---:|"]
    for metric in METRICS:
        values = [summaries[mode].get(metric, 0) for mode in MODES]
        lines.append(f"| {metric} | {values[0]:.4f} | {values[1]:.4f} | {values[2]:.4f} |")
    lines += ["", "## Go / No-Go checks", "", *checks, "", "## Raw summaries", "",
              "```json", json.dumps(summaries, indent=2), "```"]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(verdict)


if __name__ == "__main__":
    main()
