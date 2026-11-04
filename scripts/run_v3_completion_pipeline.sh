#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
STATUS=$RUNS/completion_pipeline_status.txt
LOG=$RUNS/completion_pipeline.log

mkdir -p "$RUNS"
exec 9>"$RUNS/completion_pipeline.lock"
flock -n 9 || exit 2
echo "started_at=$(date --iso-8601=seconds)" > "$STATUS"
echo "commit=$(git -C "$REPO" rev-parse HEAD)" >> "$STATUS"
: > "$LOG"

wait_for_stage() {
  local status_file=$1
  while ! grep -qx 'state=completed' "$status_file" 2>/dev/null; do
    sleep 60
  done
}

cd "$REPO"
echo "stage=fault_calibration state=waiting" >> "$STATUS"
wait_for_stage "$RUNS/fault_calibration_v3_status.txt"
if ! .venv-stateguard/bin/python scripts/summarize_fault_calibration_v3.py >> "$LOG" 2>&1; then
  echo "stage=fault_calibration state=blocked" >> "$STATUS"
  exit 1
fi
echo "stage=fault_calibration state=passed" >> "$STATUS"

echo "stage=earlier_replay state=running" >> "$STATUS"
if ! bash scripts/run_earlier_v3.sh >> "$LOG" 2>&1; then
  echo "stage=earlier_replay state=blocked" >> "$STATUS"
  exit 1
fi
if ! .venv-stateguard/bin/python - <<'PY' >> "$LOG" 2>&1
import json
from pathlib import Path

report = json.loads(Path("/data/research/stateguard_runs/round3/earlier_replay_v3.json").read_text())
raise SystemExit(0 if report["valid_injections"] == 6 and report["correct"] >= 4 else 1)
PY
then
  echo "stage=earlier_replay state=blocked" >> "$STATUS"
  exit 1
fi
echo "stage=earlier_replay state=passed" >> "$STATUS"

echo "stage=budget_ablation state=running" >> "$STATUS"
if ! bash scripts/run_budget_ablation_v3.sh >> "$LOG" 2>&1; then
  echo "stage=budget_ablation state=blocked" >> "$STATUS"
  exit 1
fi
echo "stage=budget_ablation state=completed" >> "$STATUS"

echo "stage=round3_108 state=running" >> "$STATUS"
set -a
source .env.secrets
set +a
export EXECUTOR_BASE_URL=http://127.0.0.1:8032/v1
export EXECUTOR_API_KEY=EMPTY
export EXECUTOR_MODEL=Qwen3-VL-32B-Instruct
export PYTHONPATH=/data/research/projects/StateGuard:/data/research/projects/OSWorld-StateGuard
if /data/research/ui-mopd-repro/repos/OSWorld/.venv/bin/python scripts/run_poc_matrix.py \
    --config configs/poc/osworld_round3_frozen.yaml --models configs/models.yaml \
    --resume --rerun-failed >> "$LOG" 2>&1; then
  echo "stage=round3_108 state=completed" >> "$STATUS"
  echo "state=completed" >> "$STATUS"
else
  echo "stage=round3_108 state=failed" >> "$STATUS"
  echo "state=failed" >> "$STATUS"
  exit 1
fi
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
