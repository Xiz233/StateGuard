"""Phase-13 clean-smoke comparison (A/B/C) analysis."""
import glob
import json
import sys

CONFIGS = {
    "A": "/data/research/stateguard_runs/poc_sparse_smoke_A",
    "B": "/data/research/stateguard_runs/poc_sparse_smoke_B",
    "C": "/data/research/stateguard_runs/poc_sparse_smoke_C",
}
TASKS = {
    "030eeff7-b492-4218-b312-701ec99ee0cc": "Chrome",
    "5ced85fc-fa1a-4217-95fd-0fb530545ce2": "File",
    "d53ff5ee-3b1a-431e-b2be-30ed2673079b": "Writer",
}


def load(cfg_dir):
    rows = []
    for f in sorted(glob.glob(cfg_dir + "/osworld_sparse_smoke_*/episodes/*/result.json")):
        d = json.load(open(f))
        parts = f.split("/")[-2].split("--")
        rows.append({
            "task": TASKS.get(parts[0], parts[0][:8]),
            "status": d["status"], "success": d["success"], "env": d["environment_score"],
            "steps": d["total_steps"], "guard_calls": d["guard_calls"],
            "verification_calls": d["verification_calls"], "checkpoints": d["checkpoint_count"],
            "reasons": d["checkpoint_reasons"], "dag_source": d["dag_source"],
            "dag_nodes": d["dag_node_count"], "dag_valid": d["dag_generation_valid"],
            "error": d["error"],
        })
    return rows


def main():
    data = {k: load(v) for k, v in CONFIGS.items()}
    print(f"{'cfg':4s} {'task':8s} {'succ':5s} {'env':5s} {'steps':6s} {'grd_calls':10s} {'verif':6s} {'chk':4s} {'termination'}")
    for cfg, rows in data.items():
        for r in rows:
            print(f"{cfg:4s} {r['task']:8s} {str(r['success']):5s} {r['env']:<5.1f} {r['steps']:<6d} {r['guard_calls']:<10d} {r['verification_calls']:<6d} {r['checkpoints']:<4d} {r['status']}")
    print()
    a_guard = sum(r["guard_calls"] for r in data["A"])
    b_guard = sum(r["guard_calls"] for r in data["B"])
    c_guard = sum(r["guard_calls"] for r in data["C"])
    print(f"Total guard calls  A={a_guard}  B={b_guard}  C={c_guard}")
    if a_guard:
        print(f"Gate1 B<A: {b_guard < a_guard}  reduction={(1 - b_guard / a_guard) * 100:.1f}%")
    a_succ = sum(r["success"] for r in data["A"])
    b_succ = sum(r["success"] for r in data["B"])
    c_succ = sum(r["success"] for r in data["C"])
    print(f"Clean success  A={a_succ}/3  B={b_succ}/3  C={c_succ}/3  Gate2 B>=A: {b_succ >= a_succ}")
    print("Termination reasons:", {k: [r["status"] for r in rows] for k, rows in data.items()})


if __name__ == "__main__":
    main()