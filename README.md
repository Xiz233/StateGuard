# StateGuard

Verified task state, evidence-guided recovery, dependency-aware invalidation,
and local repair/replanning for long-horizon GUI agents.

## Current publication snapshot

This update includes the v10 natural-failure runtime, adaptive verification,
training-ready raw-evidence logging, stabilization diagnostics, and the
[StructAgent fusion overlay](integrations/structagent/README.md). The overlay
combines the StructAgent workflow with StateGuard evidence management and
progressive verification; it is an experimental integration, not a claim of
improved aggregate benchmark performance.

The audited local 60-task comparison has 26 confirmed full scores versus 32
for the baseline; 26 fusion tasks ended on verification budgets without a
native score. See [the paired analysis](docs/LOCAL60_VERIFICATION_BUDGET_ANALYSIS_20261104.md).
Historical runbook paths have been anonymized and are illustrative. Configure
your own machine paths and keep provider keys in environment variables or
untracked local files. No raw rollout recordings or private credentials are
part of this update.

## Primary experiment: Natural Failure Rescue

The main experiment compares the same imperfect GUI Executor on the same
unmodified OSWorld tasks:

```text
Executor-only  vs  Executor + StateGuard
```

Results are paired by `task_id` and `run_seed` and classified as `RESCUED`,
`PRESERVED`, `REGRESSION`, or `UNRESOLVED`. Artificial fault injection is not
part of this path. Start with the paired canary pipeline:

```bash
scripts/run_v10_natural_pipeline.sh
```

Primary configs are:

```text
configs/poc/osworld_v10_executor_baseline.yaml
configs/poc/osworld_v10_natural_failure.yaml
```

Legacy fault injectors remain available only as optional controlled mechanism
diagnostics; see `experiments/poc/faults/README.md`.

## Project phases

- **Phase I — symbolic mechanism:** `VerifiedTaskState`, deterministic DAG,
  evidence/status transitions, rule verification, localization, repair, replay,
  fault injection, and offline metrics.
- **Phase II-A — real-GUI interfaces:** multimodal observations, OpenAI-compatible
  model providers, hybrid visual Guard, MLLM Executor, bounded repair loop, and
  an OSWorld adapter boundary.
- **Phase II-B — experiment-ready infrastructure:** controlled GUI diagnostics, three
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
Historical fault-matrix workflows remain documented for reproducibility, but
they are not the default v10 research design.

## Core invariants

- `EXECUTED != VERIFIED`.
- A semantic verifier/localizer may propose a causal root with explicit uncertainty.
- For controlled diagnostics, authoritative affected nodes remain
  `fault_root + graph.descendants(fault_root)`.
- Independent verified progress is preserved.
- `RepairRequest` targets the smallest invalid region; it never regenerates a plan.
- Natural runs do not construct a `FaultInjector`; intended and executed actions
  are equal unless the real environment itself diverges.
- Executor and Guard never receive controlled-fault ground truth in optional diagnostics.
- `stateguard/` never imports benchmark or experiment packages.

## Main entry points

```bash
python scripts/check_readiness.py
python scripts/run_poc_osworld.py --config configs/poc/osworld_v10_natural_failure.yaml --mode stateguard --dry-run
python scripts/prepare_osworld_poc.py --benchmark-root /path/to/OSWorld
python scripts/prepare_task_graphs.py --manifest configs/poc/selected_tasks.yaml
python scripts/review_task_graphs.py --manifest configs/poc/selected_tasks.yaml --reviewer NAME
```

PoC modes are `executor_only`, `latest_retry`, and `stateguard`. Use `--task ID`
for one task, `--tasks ID1,ID2` for a subset, `--tasks all` for a batch,
`--resume` to skip completed episodes, and `--rerun-failed` to repeat only failed
resumed episodes.
