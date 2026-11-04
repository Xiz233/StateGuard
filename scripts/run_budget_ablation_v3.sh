#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
LOG=$RUNS/budget_ablation_v3.log
STATUS=$RUNS/budget_ablation_v3_status.txt
TASK=5ced85fc-fa1a-4217-95fd-0fb530545ce2
SCENARIO=5ced85fc-fa1a-4217-95fd-0fb530545ce2--wrong_value--1
CONFIGS=(
  configs/poc/osworld_budget_x1.yaml
  configs/poc/osworld_budget_x1_5.yaml
  configs/poc/osworld_budget_x2.yaml
)

mkdir -p "$RUNS"
exec 9>"$RUNS/budget_ablation_v3.lock"
flock -n 9 || exit 2
echo "started_at=$(date --iso-8601=seconds)" > "$STATUS"
echo "commit=$(git -C "$REPO" rev-parse HEAD)" >> "$STATUS"
: > "$LOG"

cd "$REPO"
failures=0
for config in "${CONFIGS[@]}"; do
  echo "config=$config state=running" >> "$STATUS"
  if /data/research/stateguard_runs/run_smoke.sh \
      --config "$config" --models configs/models.yaml --mode stateguard \
      --task "$TASK" --scenario "$SCENARIO" --resume --rerun-failed \
      >> "$LOG" 2>&1; then
    echo "config=$config exit=0" >> "$STATUS"
  else
    code=$?
    failures=$((failures + 1))
    echo "config=$config exit=$code" >> "$STATUS"
  fi
done

echo "case_failures=$failures" >> "$STATUS"
echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
