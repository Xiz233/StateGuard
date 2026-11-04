#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
LOG=$RUNS/earlier_v3.log
STATUS=$RUNS/earlier_v3_status.txt
CONFIG=configs/poc/osworld_fault_calibration_v3.yaml
CASES=(
  '030eeff7-b492-4218-b312-701ec99ee0cc|030eeff7-b492-4218-b312-701ec99ee0cc--earlier_state_corruption--1'
  '3680a5ee-6870-426a-a997-eba929a0d25c|3680a5ee-6870-426a-a997-eba929a0d25c--earlier_state_corruption--1'
  '4127319a-8b79-4410-b58a-7a151e15f3d7|4127319a-8b79-4410-b58a-7a151e15f3d7--earlier_state_corruption--1'
  '8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14|8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--earlier_state_corruption--1'
  '99146c54-4f37-4ab8-9327-5f3291665e1e|99146c54-4f37-4ab8-9327-5f3291665e1e--earlier_state_corruption--1'
  'd53ff5ee-3b1a-431e-b2be-30ed2673079b|d53ff5ee-3b1a-431e-b2be-30ed2673079b--earlier_state_corruption--1'
)

mkdir -p "$RUNS"
exec 9>"$RUNS/earlier_v3.lock"
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

if (( failures == 0 )); then
  set -a
  source .env.secrets
  set +a
  .venv-stateguard/bin/python scripts/replay_earlier_batch.py \
    --trajectory-glob '/data/research/stateguard_runs/poc_fault_calibration_v3/osworld_fault_calibration_v3-stateguard/episodes/*--earlier_state_corruption--*/trajectory.jsonl' \
    --report /data/research/stateguard_runs/round3/earlier_replay_v3.json \
    >> "$LOG" 2>&1 || failures=$((failures + 1))
fi

echo "case_failures=$failures" >> "$STATUS"
echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
