"""Aggregate the v9 36-episode matrix results into a report (manual sec.7-5)."""
import argparse
import glob
import json
from collections import Counter

DEFAULT_BASE = ("/data/research/stateguard_runs/poc_stability_v9_matrix/"
                "osworld_v9_matrix-stateguard/episodes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()
    files = sorted(glob.glob(args.base.rstrip("/") + "/*/result.json"))
    if not files:
        print("no results yet")
        return
    rows = []
    for f in files:
        d = json.load(open(f))
        parts = f.split("/")[-2].split("--")
        ft = d["fault_events"][0]["fault_type"] if d["fault_events"] else "clean"
        rows.append({
            "task": parts[0][:8], "scenario": ft,
            "success": d["success"], "env": d["environment_score"],
            "steps": d["total_steps"], "status": d["status"],
            "inj_step": d["fault_injected_step"],
            "first_root": d["first_root_prediction"],
            "first_acc": d["first_root_accuracy"],
            "repair_cycles": d["repair_cycle_count"],
            "contracts": d.get("contracts_generated", 0),
            "guard_calls": d["guard_calls"], "executor_calls": d["executor_calls"],
            "unknown_chk": d.get("unknown_checkpoint_count", 0),
            "local_replan": d.get("local_replan_count", 0),
            "replan_success": d.get("local_replan_success_count", 0),
            "guard_fail_open": d.get("guard_parse_fail_open_count", 0),
            "strategy_normalized": d.get("guard_strategy_normalization_count", 0),
            "progress_dropped": d.get("guard_progress_update_drop_count", 0),
            "replan_fallback": d.get("replanner_fallback_count", 0),
        })
    clean = [r for r in rows if r["scenario"] == "clean"]
    faulted = [r for r in rows if r["scenario"] != "clean"]
    print(f"episodes: {len(rows)}  clean: {len(clean)}  faulted: {len(faulted)}")
    print(f"clean task success: {sum(r['success'] for r in clean)}/{len(clean)}")
    print(f"fault injection: {sum(r['inj_step'] is not None for r in faulted)}/{len(faulted)}")
    print(f"fault recovery: {sum(r['success'] for r in faulted)}/{len(faulted)}")
    print(f"first_root_acc (faulted): {sum(r['first_acc'] for r in faulted)}/{len(faulted)}")
    print(f"termination: {dict(Counter(r['status'] for r in rows))}")
    print(f"total steps={sum(r['steps'] for r in rows)}  "
          f"guard_calls={sum(r['guard_calls'] for r in rows)}  "
          f"executor_calls={sum(r['executor_calls'] for r in rows)}  "
          f"contracts={sum(r['contracts'] for r in rows)}")
    print(f"unknown_checkpoints={sum(r['unknown_chk'] for r in rows)}  "
          f"local_replan={sum(r['local_replan'] for r in rows)}  "
          f"replan_success={sum(r['replan_success'] for r in rows)}")
    print(f"guard_fail_open={sum(r['guard_fail_open'] for r in rows)}  "
          f"strategy_normalized={sum(r['strategy_normalized'] for r in rows)}  "
          f"progress_dropped={sum(r['progress_dropped'] for r in rows)}  "
          f"replan_fallback={sum(r['replan_fallback'] for r in rows)}")
    print()
    print("per-episode:")
    for r in sorted(rows, key=lambda x: (x["task"], x["scenario"])):
        print(f"  {r['task']} {r['scenario'][:22]:22s} succ={r['success']} env={r['env']:.1f} "
              f"steps={r['steps']:3d} inj@{r['inj_step']} root={r['first_root']} acc={r['first_acc']:.1f} "
              f"rc={r['repair_cycles']} contracts={r['contracts']} {r['status']}")


if __name__ == "__main__":
    main()
