# Phase II-B handoff

## State

All experiment code and contracts are complete and validated end-to-end against the
fake backend. The only remaining blockers are external model endpoints and real
OSWorld/OSWorld-Verified deployment.

## Architecture and changed areas

- Typed/bounded GUI action validation and one-retry Executor/Guard parsing.
- OSWorld backend protocol, DesktopEnv seam, health/info/close, and fake backend.
- Four concrete controlled-fault injectors with separated ground truth.
- Three-mode batch runner with clean/fault episodes, resume, rerun-failed, and dry-run.
- Bounded history, UNKNOWN verification, FINISH gate, repair/verification budgets.
- Run/episode logging, hashes/metadata, aggregate metrics, discovery and DAG review tools.
- HTTP fake model server and Phase-I/II regression and full fake E2E tests.

## Validation

- Pre-Phase-II-B baseline: 59 tests passed; mock demo and offline eval passed.
- Final suite: 77 tests passed.
- Fake readiness: `FULLY_READY`.
- Fake `executor_only`, `latest_retry`, and `stateguard` batches complete.
- StateGuard fake batch: task/recovery/root/F1/preservation = 1.0; false intervention = 0.

## External blockers

- `STATEGUARD_BASE_URL`, `STATEGUARD_API_KEY`, `STATEGUARD_MODEL`.
- `EXECUTOR_BASE_URL`, `EXECUTOR_API_KEY`, `EXECUTOR_MODEL` for Qwen3-VL-32B-Instruct.
- OSWorld/OSWorld-Verified installation, VM/Docker assets, and approved real task DAGs.

## Exact Server-2 sequence

Follow `OSWORLD_DEPLOYMENT_HANDOFF.md`, then run:

```bash
python scripts/check_readiness.py
python scripts/run_poc_osworld.py --config configs/poc/osworld_poc.yaml --mode stateguard --dry-run
python scripts/run_poc_osworld.py --config configs/poc/osworld_poc.yaml --mode stateguard --tasks all
```

Known limitation: DesktopEnv versions may require adapter-only compatibility changes;
fake-backend scores are plumbing validation, not scientific evidence.
