# Phase II-A handoff

## Changes

- Upgraded `Observation` to multimodal while retaining `snapshot` compatibility.
- Added provider config, OpenAI-compatible multimodal client, retries, and JSON errors.
- Added rule/MLLM/hybrid Guard backends; graph code remains authoritative for propagation.
- Added manual DAG loading and optional ModelClient-backed TaskCompiler.
- Added GUI Executor parsing, fixed minimal-repair prompt, bounded autonomous runtime.
- Added lazy OSWorld adapter and isolated four-fault PoC controls.
- Added provider/readiness/PoC scripts, configuration examples, logging, metrics, and tests.

## Dataflow

`Observation -> Executor proposal -> Environment -> StateGuard judgement -> deterministic
DAG invalidation -> RepairRequest -> Executor repair action -> re-verification`.

## Verification

- Phase-I baseline: 49 tests passed; mock demo and offline eval passed.
- Phase-II-A full suite: 59 tests passed.
- Real StateGuard API: not tested; credentials are not configured.
- Qwen endpoint: code/config ready, endpoint not deployed by design.
- OSWorld: adapter ready, environment/task set not installed on this server.

## Server 2 commands

```bash
cp configs/models.example.yaml configs/models.yaml
export STATEGUARD_BASE_URL=...
export STATEGUARD_API_KEY=...
export STATEGUARD_MODEL=...
export EXECUTOR_BASE_URL=...
export EXECUTOR_API_KEY=...
python scripts/check_readiness.py --config configs/models.yaml
python scripts/test_model_api.py --config configs/models.yaml --provider stateguard_api
python scripts/run_guard_visual_smoke.py --config configs/models.yaml
python scripts/run_poc_osworld.py --config configs/poc/osworld_tasks.yaml --mode stateguard
```

## Repository state and known gaps

Current base commit: `fe2a1e11d4744589163d3d183d3a31804dde603d`. Changes are left
uncommitted for review. The visual smoke requires user-supplied credentials/assets, Qwen
requires its future endpoint, and concrete OSWorld task IDs/manual DAGs must be selected
only after the verified task set is available.
