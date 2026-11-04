from __future__ import annotations

import json
from pathlib import Path


RUN = Path(
    "/data/research/stateguard_runs/poc_stability_v3/"
    "osworld_stability_v3-stateguard/episodes"
)
REPORT = Path("/data/research/stateguard_runs/round3/stability_v3.json")
FAULTS = (
    "8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--wrong_target--2",
    "bc2b57f3-686d-4ec9-87ce-edf850b7e442--no_effect--2",
    "c7c1e4c3-9e92-4eba-a4b8-689953975ea4--wrong_value--1",
)
INFRA_FAILURES = {
    "executor_parse_failed",
    "guard_parse_failed",
    "model_failed",
    "environment_failed",
    "auto_dag_failed",
}


def main() -> None:
    rows = []
    for fault_id in FAULTS:
        task_id = fault_id.split("--", 1)[0]
        path = RUN / f"{task_id}--stateguard--{fault_id}" / "result.json"
        if not path.exists():
            rows.append({"fault_id": fault_id, "missing": True})
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        rows.append({
            "fault_id": fault_id,
            "missing": False,
            "status": result.get("status"),
            "success": bool(result.get("success")),
            "total_steps": result.get("total_steps"),
            "executor_calls": result.get("executor_calls"),
        })
    infra_failures = [
        row for row in rows
        if row.get("missing") or row.get("status") in INFRA_FAILURES
    ]
    report = {
        "expected": len(FAULTS),
        "present": sum(not row["missing"] for row in rows),
        "infrastructure_failures": len(infra_failures),
        "gate_passed": not infra_failures,
        "results": rows,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
