#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
REPLAY_PID=${1:-}
REPLAY_LOG=/data/research/stateguard_runs/round2_5/v3_earlier_replay_batch.log
SMOKE_LOG=$RUNS/trust_trace_smoke.log
STATUS=$RUNS/overnight_status.txt

mkdir -p "$RUNS"
exec 9>"$RUNS/overnight.lock"
if ! flock -n 9; then
  echo "another v3 overnight pipeline is already running"
  exit 2
fi

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "commit=$(git -C "$REPO" rev-parse HEAD)"
  echo "state=waiting_for_replay"
} > "$STATUS"

if [[ -n "$REPLAY_PID" ]]; then
  while kill -0 "$REPLAY_PID" 2>/dev/null; do
    sleep 30
  done
fi

ACCURACY=$(sed -n 's/.*First Root Accuracy (earlier): \([0-9][0-9]*\)\/\([0-9][0-9]*\).*/\1\/\2/p' "$REPLAY_LOG" | tail -1)
{
  echo "replay_finished_at=$(date --iso-8601=seconds)"
  echo "earlier_root_accuracy=${ACCURACY:-unavailable}"
  echo "state=running_trust_trace_smoke"
} >> "$STATUS"

cd "$REPO"
if /data/research/stateguard_runs/run_smoke.sh \
    --config configs/poc/osworld_trust_trace_smoke.yaml \
    --models configs/models.yaml \
    --mode stateguard \
    --resume > "$SMOKE_LOG" 2>&1; then
  echo "smoke_exit=0" >> "$STATUS"
  echo "state=completed" >> "$STATUS"
else
  code=$?
  echo "smoke_exit=$code" >> "$STATUS"
  echo "state=smoke_failed" >> "$STATUS"
fi
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
