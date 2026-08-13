#!/usr/bin/env python3
"""Offline evaluation (指引.txt §27/28/36-M10):

    python scripts/run_offline_eval.py [--run-dir run] [--fault-types ...]

Runs every injectable synthetic fault case through the full
execute -> localize -> invalidate -> repair -> reverify loop and reports:
  Localization Accuracy, Affected Set F1, Recovery Success,
  Progress Preservation, Repair Radius, False Intervention.
Logs every episode under run/<episode>/ (指引.txt §28).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from examples.synthetic_tasks.tasks import TASKS
from fault_injection.injector import make_cases
from fault_injection.harness import run_episode
from fault_injection.fault_types import INJECTABLE
from eval.localization_metrics import localization_accuracy, affected_set_metrics
from eval.progress_metrics import progress_preservation_rate, repair_radius_stats
from eval.recovery_metrics import recovery_success, false_intervention_rate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="run")
    ap.add_argument("--fault-types", nargs="*",
                    default=[ft.value for ft in INJECTABLE])
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(args.fault_types)

    # 1) clean episodes: false intervention only
    clean = [run_episode(spec, spec["name"], run_dir=str(run_dir))
             for spec in TASKS]

    # 2) injected episodes
    cases = [c for c in make_cases(TASKS) if c.ground_truth["fault_type"] in wanted]
    episodes = [run_episode(c.task_spec, c.name, hints=c.hints, fixes=c.fixes,
                            gt=c.ground_truth, run_dir=str(run_dir))
                for c in cases]

    summary = {
        "episodes_injected": len(episodes),
        "episodes_clean": len(clean),
        "localization_accuracy": localization_accuracy(
            [e["predicted_root"] for e in episodes if e["predicted_root"]],
            [c.ground_truth["fault_root"] for e, c in zip(episodes, cases)
             if e["predicted_root"]]),
        "affected_set_f1": affected_set_metrics(
            [e["predicted_affected"] for e in episodes if e["predicted_affected"]],
            [c.ground_truth["affected_nodes"] for e, c in zip(episodes, cases)
             if e["predicted_affected"]]),
        "recovery_success": recovery_success([e["recovered"] for e in episodes]),
        "progress_preservation": progress_preservation_rate(
            [e["preserved_nodes"] for e in episodes],
            [e["verified_before_failure"] for e in episodes]),
        "repair_radius": repair_radius_stats(
            [e["reactivated"] for e in episodes],
            [e["repair_actions"] for e in episodes]),
        "false_intervention_rate": false_intervention_rate(
            [e["contradictions"] for e in clean]),
    }
    with open(run_dir / "metrics_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"=== StateGuard offline eval: {len(episodes)} injected + "
          f"{len(clean)} clean episodes -> {run_dir}/ ===")
    print(f"Localization Accuracy      {summary['localization_accuracy']:.3f}")
    p, r, f1 = summary["affected_set_f1"]
    print(f"Affected Set Precision     {p:.3f}")
    print(f"Affected Set Recall        {r:.3f}")
    print(f"Affected Set F1            {f1:.3f}")
    print(f"Recovery Success           {summary['recovery_success']:.3f}")
    print(f"Progress Preservation      {summary['progress_preservation']:.3f}")
    radius = summary["repair_radius"]
    print(f"Repair Radius (reactivated){radius['reactivated_nodes_mean']:.2f} mean")
    print(f"Repair Radius (actions)    {radius['repair_actions_mean']:.2f} mean")
    print(f"False Intervention Rate    {summary['false_intervention_rate']:.3f}")

    failed = [e["episode"] for e in episodes
              if e["root_correct"] is False or not e["recovered"]]
    if failed:
        print(f"\nWARNING: imperfect episodes: {failed}")


if __name__ == "__main__":
    main()
