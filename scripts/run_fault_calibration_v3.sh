#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
LOG=$RUNS/fault_calibration_v3.log
STATUS=$RUNS/fault_calibration_v3_status.txt
CONFIG=configs/poc/osworld_fault_calibration_v3.yaml
CASES=(
  '3680a5ee-6870-426a-a997-eba929a0d25c|3680a5ee-6870-426a-a997-eba929a0d25c--earlier_state_corruption--1'
  '3680a5ee-6870-426a-a997-eba929a0d25c|3680a5ee-6870-426a-a997-eba929a0d25c--wrong_value--2'
  '6f81754e-285d-4ce0-b59e-af7edb02d108|6f81754e-285d-4ce0-b59e-af7edb02d108--wrong_target--1'
  '8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14|8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--wrong_target--2'
  'aad10cd7-9337-4b62-b704-a857848cedf2|aad10cd7-9337-4b62-b704-a857848cedf2--no_effect--2'
  'bc2b57f3-686d-4ec9-87ce-edf850b7e442|bc2b57f3-686d-4ec9-87ce-edf850b7e442--no_effect--2'
  'c7c1e4c3-9e92-4eba-a4b8-689953975ea4|c7c1e4c3-9e92-4eba-a4b8-689953975ea4--wrong_value--1'
)

mkdir -p "$RUNS"
exec 9>"$RUNS/fault_calibration_v3.lock"
flock -n 9 || exit 2
echo "started_at=$(date --iso-8601=seconds)" > "$STATUS"
echo "commit=$(git -C "$REPO" rev-parse HEAD)" >> "$STATUS"
: > "$LOG"

cd "$REPO"
failures=0
for item in "${CASES[@]}"; do
  IFS='|' read -r task scenario <<< "$item"
  echo "task=$task scenario=$scenario state=running" >> "$STATUS"
  if /data/research/stateguard_runs/run_smoke.sh \
      --config "$CONFIG" --models configs/models.yaml --mode stateguard \
      --task "$task" --scenario "$scenario" --resume --rerun-failed \
      >> "$LOG" 2>&1; then
    echo "task=$task scenario=$scenario exit=0" >> "$STATUS"
  else
    code=$?
    failures=$((failures + 1))
    echo "task=$task scenario=$scenario exit=$code" >> "$STATUS"
  fi
done

echo "case_failures=$failures" >> "$STATUS"
echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
