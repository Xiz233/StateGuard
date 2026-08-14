# StateGuard

Verified task state, causal fault localization, dependency-aware invalidation,
and minimal repair for long-horizon GUI agents.

## Project phases

- **Phase I — symbolic mechanism:** `VerifiedTaskState`, deterministic DAG,
  evidence/status transitions, rule verification, localization, repair, replay,
  fault injection, and offline metrics.
- **Phase II-A — real-GUI interfaces:** multimodal observations, OpenAI-compatible
  model providers, hybrid visual Guard, MLLM Executor, bounded repair loop, and
  an OSWorld adapter boundary.
- **Phase II-B — experiment-ready infrastructure:** controlled GUI faults, three
  PoC modes, fake/full backend contracts, batch/resume/dry-run, task discovery and
  manual DAG approval, paper-grade logging, metrics, and readiness checks.

Real StateGuard/Qwen model endpoints and real OSWorld deployment remain external.
No model weights, training pipeline, benchmark assets, or hidden evaluator data are
included.

## Quick validation

```bash
pip install -e .
pytest -q
python scripts/run_mock_demo.py
python scripts/run_offline_eval.py
python scripts/check_readiness.py --backend fake
python scripts/run_poc_osworld.py --config configs/poc/fake_osworld.yaml --mode stateguard
```

The fake backend exercises the complete experiment plumbing but produces no research
result. For real deployment, follow `docs/OSWORLD_DEPLOYMENT_HANDOFF.md`.

## Core invariants

- `EXECUTED != VERIFIED`.
- A semantic verifier/localizer selects only `fault_root`.
- Authoritative affected nodes are `fault_root + graph.descendants(fault_root)`.
- Independent verified progress is preserved.
- `RepairRequest` targets the smallest invalid region; it never regenerates a plan.
- Executor and Guard never receive controlled-fault ground truth.
- `stateguard/` never imports benchmark or experiment packages.

## Main entry points

```bash
python scripts/check_readiness.py
python scripts/run_poc_osworld.py --config configs/poc/osworld_poc.yaml --mode stateguard --dry-run
python scripts/prepare_osworld_poc.py --benchmark-root /path/to/OSWorld
python scripts/prepare_task_graphs.py --manifest configs/poc/selected_tasks.yaml
python scripts/review_task_graphs.py --manifest configs/poc/selected_tasks.yaml --reviewer NAME
```

PoC modes are `executor_only`, `latest_retry`, and `stateguard`. Use `--task ID`
for one task, `--tasks all` for a batch, `--resume` to skip completed episodes, and
`--rerun-failed` to repeat only failed resumed episodes.
