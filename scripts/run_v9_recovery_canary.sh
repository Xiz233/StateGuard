#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/poc_stability_v9_recovery_canary
CONFIG=configs/poc/osworld_v9_recovery_canary.yaml
LOG=$RUNS/canary.log
STATUS=$RUNS/canary_status.txt
BASE=$RUNS/osworld_v9_recovery_canary-stateguard/episodes
CASES=(
  'c7c1e4c3-9e92-4eba-a4b8-689953975ea4|clean'
  'aad10cd7-9337-4b62-b704-a857848cedf2|aad10cd7-9337-4b62-b704-a857848cedf2--wrong_value--1'
  '8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14|8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--earlier_state_corruption--1'
)

mkdir -p "$RUNS"
exec 9>"$RUNS/canary.lock"
flock -n 9 || exit 2
{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "commit=$(git -C "$REPO" rev-parse HEAD)"
  echo "cases=${#CASES[@]}"
} > "$STATUS"
: > "$LOG"

cd "$REPO"
failures=0
for item in "${CASES[@]}"; do
  IFS='|' read -r task scenario <<< "$item"
  echo "task=$task scenario=$scenario state=running" >> "$STATUS"
  if /data/research/stateguard_runs/run_smoke.sh \
      --config "$CONFIG" --models configs/models.yaml --mode stateguard \
      --task "$task" --scenario "$scenario" --resume --rerun-failed --allow-dirty \
      >> "$LOG" 2>&1; then
    echo "task=$task scenario=$scenario exit=0" >> "$STATUS"
  else
    code=$?
    failures=$((failures + 1))
    echo "task=$task scenario=$scenario exit=$code" >> "$STATUS"
  fi
done

.venv-stateguard/bin/python scripts/report_v9_matrix.py --base "$BASE" \
  > "$RUNS/canary_report.txt" 2>&1
echo "case_process_failures=$failures" >> "$STATUS"
echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
