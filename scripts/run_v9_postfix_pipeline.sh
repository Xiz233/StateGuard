#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
ROOT=/data/research/stateguard_runs/v9_postfix_pipeline
CANARY_ROOT=/data/research/stateguard_runs/poc_stability_v9_recovery_canary
CANARY_EPISODES=$CANARY_ROOT/osworld_v9_recovery_canary-stateguard/episodes
STATUS=$ROOT/status.txt
LOG=$ROOT/pipeline.log

mkdir -p "$ROOT"
exec 9>"$ROOT/pipeline.lock"
flock -n 9 || exit 2
{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "commit=$(git -C "$REPO" rev-parse HEAD)"
  echo "state=waiting_for_canary"
} > "$STATUS"

while ! grep -q '^state=completed$' "$CANARY_ROOT/canary_status.txt" 2>/dev/null; do
  if ! pgrep -f 'scripts/run_v9_recovery_canary.sh' >/dev/null; then
    echo "state=blocked_canary_not_running" >> "$STATUS"
    exit 1
  fi
  sleep 60
done

if ! "$REPO/.venv-stateguard/bin/python" - "$CANARY_EPISODES" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
results = [json.loads(path.read_text()) for path in sorted(root.glob("*/result.json"))]
framework_failures = {
    "guard_parse_failed", "plan_revision_failed", "executor_parse_failed",
    "environment_failed", "model_failed", "auto_dag_failed",
}
errors = []
if len(results) != 3:
    errors.append(f"expected 3 canary results, found {len(results)}")
for result in results:
    if result.get("status") in framework_failures:
        errors.append(f"framework failure: {result.get('status')}: {result.get('error')}")
    if result.get("contracts_generated", 0) < 1:
        errors.append("canary produced no adaptive contract")
    replans = result.get("local_replan_count", 0)
    if result.get("local_replan_success_count", 0) < replans:
        errors.append(f"local replan did not apply: {result.get('error')}")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("canary acceptance passed")
PY
then
  echo "state=canary_failed" >> "$STATUS"
  exit 1
fi

cd "$REPO"
echo "state=running_stateguard_matrix" >> "$STATUS"
/data/research/stateguard_runs/run_smoke.sh \
  --config configs/poc/osworld_v9_fixed_matrix.yaml \
  --models configs/models.yaml --mode stateguard --resume --rerun-failed \
  >> "$LOG" 2>&1

.venv-stateguard/bin/python scripts/report_v9_matrix.py \
  --base /data/research/stateguard_runs/poc_stability_v9_fixed_matrix/osworld_v9_fixed_matrix-stateguard/episodes \
  > "$ROOT/stateguard_report.txt" 2>&1

echo "state=running_executor_baseline" >> "$STATUS"
/data/research/stateguard_runs/run_smoke.sh \
  --config configs/poc/osworld_v9_executor_baseline.yaml \
  --models configs/models.yaml --mode executor_only --resume --rerun-failed \
  >> "$LOG" 2>&1

.venv-stateguard/bin/python scripts/report_v9_matrix.py \
  --base /data/research/stateguard_runs/poc_stability_v9_executor_baseline/osworld_v9_executor_baseline-executor_only/episodes \
  > "$ROOT/baseline_report.txt" 2>&1

echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
