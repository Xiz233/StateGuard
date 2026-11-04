#!/usr/bin/env bash
set -uo pipefail

REPO=/data/research/projects/StateGuard
RUNS=/data/research/stateguard_runs/round3
LOG=$RUNS/clean_catalog_v3.log
STATUS=$RUNS/clean_catalog_v3_status.txt
TASKS=(
  3680a5ee-6870-426a-a997-eba929a0d25c
  4127319a-8b79-4410-b58a-7a151e15f3d7
  6f81754e-285d-4ce0-b59e-af7edb02d108
  8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14
  99146c54-4f37-4ab8-9327-5f3291665e1e
  aad10cd7-9337-4b62-b704-a857848cedf2
  66399b0d-8fda-4618-95c4-bfc6191617e9
  bc2b57f3-686d-4ec9-87ce-edf850b7e442
  c7c1e4c3-9e92-4eba-a4b8-689953975ea4
)

mkdir -p "$RUNS"
exec 9>"$RUNS/clean_catalog_v3.lock"
flock -n 9 || exit 2
echo "started_at=$(date --iso-8601=seconds)" > "$STATUS"
echo "commit=$(git -C "$REPO" rev-parse HEAD)" >> "$STATUS"
: > "$LOG"

cd "$REPO"
failures=0
for task in "${TASKS[@]}"; do
  echo "task=$task state=running" >> "$STATUS"
  if /data/research/stateguard_runs/run_smoke.sh \
      --config configs/poc/osworld_clean_catalog_v3.yaml \
      --models configs/models.yaml --mode stateguard \
      --task "$task" --resume --rerun-failed >> "$LOG" 2>&1; then
    echo "task=$task exit=0" >> "$STATUS"
  else
    code=$?
    failures=$((failures + 1))
    echo "task=$task exit=$code" >> "$STATUS"
  fi
done

.venv-stateguard/bin/python scripts/build_clean_trajectory_catalog.py \
  --trajectory-glob '/data/research/stateguard_runs/poc_clean_catalog_v3/**/episodes/*--stateguard--clean/trajectory.jsonl' \
  --trajectory-glob '/data/research/stateguard_runs/poc_v1_108/osworld_stateguard_poc-stateguard/episodes/030eeff7-b492-4218-b312-701ec99ee0cc--stateguard--clean/trajectory.jsonl' \
  --trajectory-glob '/data/research/stateguard_runs/poc_v1_108/osworld_stateguard_poc-stateguard/episodes/5ced85fc-fa1a-4217-95fd-0fb530545ce2--stateguard--clean/trajectory.jsonl' \
  --trajectory-glob '/data/research/stateguard_runs/poc_v1_108/osworld_stateguard_poc-stateguard/episodes/d53ff5ee-3b1a-431e-b2be-30ed2673079b--stateguard--clean/trajectory.jsonl' \
  >> "$LOG" 2>&1

echo "task_failures=$failures" >> "$STATUS"
echo "state=completed" >> "$STATUS"
echo "finished_at=$(date --iso-8601=seconds)" >> "$STATUS"
