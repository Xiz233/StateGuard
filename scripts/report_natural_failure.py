#!/usr/bin/env python3
"""Generate the primary paired Natural Failure Rescue report."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from experiments.poc.natural_failures import analyze_episode


PAIR_LABELS = {
    (False, True): "RESCUED",
    (True, True): "PRESERVED",
    (True, False): "REGRESSION",
    (False, False): "UNRESOLVED",
}


def load_episodes(root: str | Path) -> dict[tuple[str, int], dict]:
    rows = {}
    for path in sorted(Path(root).glob("*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        metrics = result.get("metrics") or {}
        task_id = metrics.get("task_id")
        seed = metrics.get("run_seed")
        if task_id is None or seed is None:
            parts = path.parent.name.split("--")
            task_id = parts[0]
            seed_part = next((part for part in parts if part.startswith("seed-")), "seed-0")
            seed = int(seed_part.removeprefix("seed-"))
        rows[(str(task_id), int(seed))] = {
            "path": path, "result": result, "analysis": analyze_episode(path.parent)}
    return rows


def build_report(baseline_root, stateguard_root, expected=None):
    baseline = load_episodes(baseline_root)
    guarded = load_episodes(stateguard_root)
    keys = sorted(set(baseline) | set(guarded))
    missing_baseline = [key for key in keys if key not in baseline]
    missing_stateguard = [key for key in keys if key not in guarded]
    if expected is not None:
        if len(baseline) != expected or len(guarded) != expected:
            raise ValueError(
                f"incomplete paired experiment: expected {expected} per mode, "
                f"found baseline={len(baseline)}, stateguard={len(guarded)}")
    if missing_baseline or missing_stateguard:
        raise ValueError(
            "unpaired results: "
            f"missing baseline={missing_baseline}, missing stateguard={missing_stateguard}")

    pairs = []
    for key in keys:
        b, s = baseline[key], guarded[key]
        br, sr = b["result"], s["result"]
        label = PAIR_LABELS[(bool(br.get("success")), bool(sr.get("success")))]
        pairs.append({
            "task_id": key[0], "run_seed": key[1], "pair_category": label,
            "baseline_status": br.get("status"),
            "stateguard_status": sr.get("status"),
            "baseline_success": bool(br.get("success")),
            "stateguard_success": bool(sr.get("success")),
            "baseline_failure_mode": b["analysis"]["primary_failure_mode"],
            "stateguard_failure_mode": s["analysis"]["primary_failure_mode"],
            "first_suspicious_step": s["analysis"]["earliest_suspicious_step"],
            "first_intervention": s["analysis"]["first_intervention"],
            "baseline_steps": br.get("total_steps", 0),
            "stateguard_steps": sr.get("total_steps", 0),
            "guard_calls": sr.get("guard_calls", 0),
            "unknown_count": sr.get("unknown_checkpoint_count", 0),
            "repair_count": sr.get("repair_cycle_count", 0),
            "replan_count": sr.get("local_replan_count", 0),
            "verification_complete": s["analysis"]["verification_complete"],
            "baseline_episode": str(b["path"].parent),
            "stateguard_episode": str(s["path"].parent),
        })
    counts = {label: sum(row["pair_category"] == label for row in pairs)
              for label in PAIR_LABELS.values()}
    baseline_fail = counts["RESCUED"] + counts["UNRESOLVED"]
    baseline_success = counts["PRESERVED"] + counts["REGRESSION"]
    return {
        "pairs": len(pairs),
        "baseline_success": sum(row["baseline_success"] for row in pairs),
        "stateguard_success": sum(row["stateguard_success"] for row in pairs),
        **{label.lower(): value for label, value in counts.items()},
        "natural_failure_rescue_rate": counts["RESCUED"] / baseline_fail if baseline_fail else 0,
        "regression_rate": counts["REGRESSION"] / baseline_success if baseline_success else 0,
        "net_rescue": counts["RESCUED"] - counts["REGRESSION"],
        "paired_success_delta": (
            sum(row["stateguard_success"] for row in pairs)
            - sum(row["baseline_success"] for row in pairs)) / len(pairs) if pairs else 0,
        "baseline_total_steps": sum(row["baseline_steps"] for row in pairs),
        "stateguard_total_steps": sum(row["stateguard_steps"] for row in pairs),
        "guard_calls": sum(row["guard_calls"] for row in pairs),
        "unknown_count": sum(row["unknown_count"] for row in pairs),
        "repair_count": sum(row["repair_count"] for row in pairs),
        "replan_count": sum(row["replan_count"] for row in pairs),
        "verification_complete_count": sum(row["verification_complete"] for row in pairs),
        "paired_table": pairs,
    }


def markdown(report) -> str:
    n = report["pairs"]
    lines = [
        "# Natural Failure Rescue Report", "",
        "## Summary", "",
        f"- Executor-only: {report['baseline_success']} / {n}",
        f"- StateGuard: {report['stateguard_success']} / {n}",
        f"- RESCUED: {report['rescued']}",
        f"- PRESERVED: {report['preserved']}",
        f"- REGRESSION: {report['regression']}",
        f"- UNRESOLVED: {report['unresolved']}",
        f"- Natural Failure Rescue Rate: {report['natural_failure_rescue_rate']:.3f}",
        f"- Regression Rate: {report['regression_rate']:.3f}",
        f"- Net Rescue: {report['net_rescue']}",
        f"- Paired success delta: {report['paired_success_delta']:+.3f}", "",
        "## Paired Table", "",
        "| task/seed | pair | baseline | StateGuard | baseline failure | "
        "StateGuard failure | steps B/S | guard | repair | replan | verified |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["paired_table"]:
        lines.append(
            f"| {row['task_id'][:8]}/{row['run_seed']} | {row['pair_category']} | "
            f"{row['baseline_status']} | {row['stateguard_status']} | "
            f"{row['baseline_failure_mode'] or '-'} | {row['stateguard_failure_mode'] or '-'} | "
            f"{row['baseline_steps']}/{row['stateguard_steps']} | {row['guard_calls']} | "
            f"{row['repair_count']} | {row['replan_count']} | "
            f"{'yes' if row['verification_complete'] else 'no'} |")
    for label in ("RESCUED", "UNRESOLVED", "REGRESSION"):
        selected = [row for row in report["paired_table"] if row["pair_category"] == label]
        lines.extend(["", f"## {label.title()} Cases", ""])
        if not selected:
            lines.append("None.")
        for row in selected:
            lines.extend([
                f"### {row['task_id']} / seed {row['run_seed']}", "",
                f"- Baseline: `{row['baseline_status']}`; "
                f"failure mode: `{row['baseline_failure_mode']}`",
                f"- StateGuard: `{row['stateguard_status']}`; "
                f"failure mode: `{row['stateguard_failure_mode']}`",
                f"- First suspicious step: `{row['first_suspicious_step']}`",
                f"- First intervention: `{row['first_intervention']}`",
                f"- Guard/repair/replan: {row['guard_calls']}/"
                f"{row['repair_count']}/{row['replan_count']}",
                f"- Baseline episode: `{row['baseline_episode']}`",
                f"- StateGuard episode: `{row['stateguard_episode']}`",
            ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--stateguard", required=True)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--output")
    parser.add_argument("--json-output")
    parser.add_argument("--csv-output")
    args = parser.parse_args()
    report = build_report(args.baseline, args.stateguard, args.expected)
    rendered = markdown(report)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.csv_output:
        rows = report["paired_table"]
        with Path(args.csv_output).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys() if rows else ())
            if rows:
                writer.writeheader(); writer.writerows(rows)


if __name__ == "__main__":
    main()
