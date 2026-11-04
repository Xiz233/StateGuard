from __future__ import annotations

import json
from pathlib import Path


RUN = Path(
    "/data/research/stateguard_runs/poc_fault_calibration_v3/"
    "osworld_fault_calibration_v3-stateguard/episodes"
)
REPORT = Path("/data/research/stateguard_runs/round3/fault_calibration_v3.json")
FAULTS = (
    "3680a5ee-6870-426a-a997-eba929a0d25c--earlier_state_corruption--1",
    "3680a5ee-6870-426a-a997-eba929a0d25c--wrong_value--2",
    "6f81754e-285d-4ce0-b59e-af7edb02d108--wrong_target--1",
    "8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--wrong_target--2",
    "aad10cd7-9337-4b62-b704-a857848cedf2--no_effect--2",
    "bc2b57f3-686d-4ec9-87ce-edf850b7e442--no_effect--2",
    "c7c1e4c3-9e92-4eba-a4b8-689953975ea4--wrong_value--1",
)


def main() -> None:
    rows = []
    for fault_id in FAULTS:
        task_id = fault_id.split("--", 1)[0]
        path = RUN / f"{task_id}--stateguard--{fault_id}" / "result.json"
        if not path.exists():
            rows.append({"fault_id": fault_id, "missing": True})
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        metrics = result.get("metrics", {})
        rows.append({
            "fault_id": fault_id,
            "missing": False,
            "injected": bool(metrics.get("fault_injected")),
            "effect_observed": bool(metrics.get("fault_effect_observed")),
            "success": bool(result.get("success")),
            "status": result.get("status"),
            "first_root_accuracy": result.get("first_root_accuracy", 0),
            "eventual_root_accuracy": result.get("eventual_root_accuracy", 0),
        })
    present = [row for row in rows if not row["missing"]]
    injected = sum(row["injected"] for row in present)
    effect = sum(row["effect_observed"] for row in present)
    report = {
        "expected": len(FAULTS),
        "present": len(present),
        "injected": injected,
        "injection_validity": injected / len(FAULTS),
        "effect_observed_rate": effect / len(FAULTS),
        "recovery_success_rate": sum(row["success"] for row in present) / len(FAULTS),
        "gate_passed": len(present) == len(FAULTS) and injected / len(FAULTS) >= 0.95,
        "results": rows,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
