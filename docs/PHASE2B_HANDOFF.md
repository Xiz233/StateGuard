# Phase II-B handoff

## State

All experiment code and contracts are complete and validated end-to-end against the
fake backend. The only remaining blockers are external model endpoints and real
OSWorld/OSWorld-Verified deployment.

Phase II-B implementation commit: `5636309f8b0442686e95fa24b8c8190c3d078c5d`.

## Architecture and changed areas

- Typed/bounded GUI action validation and one-retry Executor/Guard parsing.
- OSWorld backend protocol, DesktopEnv seam, health/info/close, and fake backend.
- Four concrete controlled-fault injectors with separated ground truth.
- Three-mode batch runner with clean/fault episodes, resume, rerun-failed, and dry-run.
- Bounded history, UNKNOWN verification, FINISH gate, repair/verification budgets.
- Run/episode logging, hashes/metadata, aggregate metrics, discovery and DAG review tools.
- HTTP fake model server and Phase-I/II regression and full fake E2E tests.
- Validity cleanup separates injection/exposure/detection/repair timing, removes
  latest-retry timing leakage, and derives primary metrics from trajectory behavior.

## Validation

- Pre-Phase-II-B baseline: 59 tests passed; mock demo and offline eval passed.
- Experiment-validity suite: 90 tests passed before final acceptance rerun.
- Fake readiness: `FULLY_READY`.
- Fake `executor_only`, `latest_retry`, and `stateguard` batches complete.
- StateGuard fake batch: task/recovery/root/F1/preservation = 1.0; false intervention = 0.
- Four-node latent E2E injects at S2, exposes at S4, first diagnoses S2, preserves S1,
  invalidates S3/S4, and repairs without re-executing S1.

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
