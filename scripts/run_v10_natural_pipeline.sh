#!/usr/bin/env bash
set -euo pipefail

REPO=/data/research/projects/StateGuard
ROOT=/data/research/stateguard_runs/natural_failure_v10_pipeline
RUN=/data/research/stateguard_runs/run_smoke.sh
PYTHON=$REPO/.venv-stateguard/bin/python
STATUS=$ROOT/status.txt
LOG=$ROOT/pipeline.log

CANARY_BASE=$ROOT/../natural_failure_v10_canary_executor/osworld_v10_natural_canary_executor-executor_only/episodes
CANARY_GUARD=$ROOT/../natural_failure_v10_canary_stateguard/osworld_v10_natural_canary_stateguard-stateguard/episodes
FULL_BASE=$ROOT/../natural_failure_v10_executor/osworld_v10_natural_executor-executor_only/episodes
FULL_GUARD=$ROOT/../natural_failure_v10_stateguard/osworld_v10_natural_stateguard-stateguard/episodes

mkdir -p "$ROOT"
exec 9>"$ROOT/pipeline.lock"
flock -n 9 || { echo "another v10 pipeline owns the lock" >&2; exit 2; }
exec > >(tee -a "$LOG") 2>&1

state() {
  printf 'state=%s at=%s\n' "$1" "$(date --iso-8601=seconds)" >> "$STATUS"
}

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "commit=$(git -C "$REPO" rev-parse HEAD)"
  echo "design=natural_failure"
} > "$STATUS"

cd "$REPO"
state preflight
"$RUN" --config configs/poc/osworld_v10_natural_canary_executor.yaml \
  --models configs/models.yaml --mode executor_only --dry-run
"$RUN" --config configs/poc/osworld_v10_natural_canary_stateguard.yaml \
  --models configs/models.yaml --mode stateguard --dry-run

state running_canary_executor
"$RUN" --config configs/poc/osworld_v10_natural_canary_executor.yaml \
  --models configs/models.yaml --mode executor_only --resume
"$PYTHON" scripts/check_natural_completeness.py \
  --episodes "$CANARY_BASE" --expected 4

state running_canary_stateguard
"$RUN" --config configs/poc/osworld_v10_natural_canary_stateguard.yaml \
  --models configs/models.yaml --mode stateguard --resume
"$PYTHON" scripts/check_natural_completeness.py \
  --episodes "$CANARY_GUARD" --expected 4

state reporting_canary
"$PYTHON" scripts/report_natural_failure.py \
  --baseline "$CANARY_BASE" --stateguard "$CANARY_GUARD" --expected 4 \
  --output "$ROOT/canary_report.md" \
  --json-output "$ROOT/canary_report.json" \
  --csv-output "$ROOT/canary_pairs.csv"

rescued=$("$PYTHON" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["rescued"])' \
  "$ROOT/canary_report.json")
if (( rescued < 1 )); then
  state blocked_no_canary_rescue
  echo "canary produced no natural-failure rescue; inspect paired trajectories before scaling"
  exit 3
fi

state running_full_executor
"$RUN" --config configs/poc/osworld_v10_executor_baseline.yaml \
  --models configs/models.yaml --mode executor_only --resume
"$PYTHON" scripts/check_natural_completeness.py \
  --episodes "$FULL_BASE" --expected 12 --allow-framework-failures

state running_full_stateguard
"$RUN" --config configs/poc/osworld_v10_natural_failure.yaml \
  --models configs/models.yaml --mode stateguard --resume
"$PYTHON" scripts/check_natural_completeness.py \
  --episodes "$FULL_GUARD" --expected 12 --allow-framework-failures

state reporting_full
"$PYTHON" scripts/report_natural_failure.py \
  --baseline "$FULL_BASE" --stateguard "$FULL_GUARD" --expected 12 \
  --output "$ROOT/final_report.md" \
  --json-output "$ROOT/final_report.json" \
  --csv-output "$ROOT/final_pairs.csv"

state completed
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
