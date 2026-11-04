#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
STATUS=$RUNS/post_fix_pipeline_status.txt
LOG=$RUNS/post_fix_pipeline.log

mkdir -p "$RUNS"
exec 9>"$RUNS/post_fix_pipeline.lock"
flock -n 9 || exit 2
echo "started_at=$(date --iso-8601=seconds)" > "$STATUS"
echo "commit=$(git -C "$REPO" rev-parse HEAD)" >> "$STATUS"
: > "$LOG"
cd "$REPO"

echo "stage=stability state=running" >> "$STATUS"
if ! bash scripts/run_stability_v3.sh >> "$LOG" 2>&1; then
  echo "stage=stability state=blocked" >> "$STATUS"
  exit 1
fi
if ! .venv-stateguard/bin/python scripts/summarize_stability_v3.py >> "$LOG" 2>&1; then
  echo "stage=stability state=blocked" >> "$STATUS"
  exit 1
fi
echo "stage=stability state=passed" >> "$STATUS"

echo "stage=budget_ablation state=running" >> "$STATUS"
if ! bash scripts/run_budget_ablation_v3.sh >> "$LOG" 2>&1; then
  echo "stage=budget_ablation state=blocked" >> "$STATUS"
  exit 1
fi
if ! grep -qx 'case_failures=0' "$RUNS/budget_ablation_v3_status.txt"; then
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
