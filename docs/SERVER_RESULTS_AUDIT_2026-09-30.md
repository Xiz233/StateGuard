# StateGuard Server Results Audit

Date: 2026-09-30\
Server: `researcher@example-host`\
Repository: `/data/research/projects/StateGuard`\
Branch / audited implementation base: `feature/v10-natural-failure` / `4f1bf4b`\
Result root: `/data/research/stateguard_runs` (8.1 GB)\
Regression: `261 passed in 9.39s`

## Current Status

- Server connection is healthy.
- No StateGuard/OSWorld experiment is currently running.
- Latest completed result is stabilization v1, finalized on 2026-09-21.
- `/data` has about 4.3 TB free.
- The implementation worktree is dirty: training-ready logging, evaluator probing, UNKNOWN stabilization and tests are present but uncommitted. The two result reports are committed separately.

## Result Tiers

### Tier A: Strict Paired Natural-Failure Evidence

Source: `/data/research/stateguard_runs/natural_failure_v10_pipeline/canary_report.json`

| Metric | Executor-only | StateGuard |
|---|---:|---:|
| Pairs | 4 | 4 |
| Successful | 2 | 1 |
| Total steps | 116 | 158 |
| Model calls | 116 | 380 |
| Guard calls | 0 | 109 |

Pair outcome: 0 RESCUED, 1 PRESERVED, 1 REGRESSION, 2 UNRESOLVED. Net rescue is -1 and paired success delta is -25pp. This is the strongest task-performance comparison because task and seed are paired, but it is currently a negative result.

Mechanism observations remain usable: five local replans were applied, two repair cycles ran, 77 UNKNOWN decisions were generated, and none changed the evidence source. Applied intervention count is therefore not a proxy for task uplift.

### Tier B: Controlled-Fault Capability

| Run | Episodes | Task success | Recovery | Root accuracy | Main use |
|---|---:|---:|---:|---:|---|
| sparse fault smoke | 9 (3 clean + 6 fault) | 7/9 | 4/6 | 1/6 | strongest small controlled recovery result |
| hybrid fault smoke | 9 | 6/9 | 3/6 | 0/6 | shows detection lost under blunt fail-open |
| trust-trace smoke | 9 | 7/9 | 4/6 | 0/6 | state preservation / suspicion validation |
| v9 matrix | 36 | 11/36 | 7/21 fault cases | 5/21 | broader fault matrix |
| v1 StateGuard | 36 | 7/36 | 6/36 aggregate field | 6/36 | early implementation history |

The small-run headline is 4/6 recovery (66.7%). The broader v9 headline is 100% declared fault injection among 21 fault episodes, 7/21 recovery and 5/21 first-root localization, as reconstructed in `docs/V9_MATRIX_REPORT.md`.

Do not compare these percentages directly with full OSWorld task success: the denominators contain selected clean/fault scenarios and use declared injections.

### Tier C: Verification Efficiency

Source runs:

- `/data/research/stateguard_runs/poc_sparse_smoke_A`
- `/data/research/stateguard_runs/poc_sparse_smoke_B`
- `/data/research/stateguard_runs/poc_sparse_smoke_H`

Dense verification used 22 Guard calls for 3/3 clean success. Sparse and hybrid each used 13 calls for 3/3 success. The observed reduction is 40.9% with no success loss on this three-task subset.

### Tier D: Training-Data and Observability Evidence

Training logging canary:

- root: `/data/research/stateguard_runs/training_logging_v1_canary`;
- 3 real episodes + 1 deterministic fault episode;
- 4/4 integrity PASS;
- 163 events, 186 model calls, 77 transitions, 450 artifact records;
- 37/37 real UNKNOWN decisions have later traceable events.

Stabilization v1:

- root: `/data/research/stateguard_runs/stabilization_v1`;
- 12 real mixed OSWorld tasks, 2 successful;
- 185 environment steps and 354 model calls;
- 1,172 logical events and 994 artifact records;
- 10/354 (2.8%) true schema/semantic failures;
- 73/73 UNKNOWN decisions have terminal resolution records;
- 11/12 strict integrity PASS;
- 9 episodes terminated explicitly on UNKNOWN budget rather than running indefinitely.

Evaluator audit:

- output: `/data/research/stateguard_runs/evaluator_audit_v1/results.json`;
- five real task types inspected;
- adapter now preserves component metric, observed/expected summary, score, pass/fail, artifact identity and exception;
- native scalar score is unchanged;
- evaluator metadata is annotation-only and must not enter model input.

## Historical Aggregates

### Initial 36-Episode Comparison

`/data/research/stateguard_runs/poc_v1_108` contains three 36-episode modes:

| Mode | Success | Model calls | Latency (s) |
|---|---:|---:|---:|
| executor_only | 10/36 (27.8%) | 1,544 | 7,534 |
| latest_retry | 9/36 (25.0%) | 1,548 | 8,888 |
| StateGuard | 7/36 (19.4%) | 993 | 24,196 |

This early version did not improve task success. Its usable contributions are diagnostic: 16.7% first-root accuracy, 20.8% eventual-root accuracy, affected-set F1 0.464, and strict progress preservation 95.8%. It also exposes high repair/intervention cost.

### v9 Aggregate Versus Executor Baseline

| Run | Success | Notes |
|---|---:|---|
| v9 matrix StateGuard | 11/36 (30.6%) | seed 20260904, Executor `stateguard_api` |
| v9 executor baseline | 3/36 (8.3%) | seed 20260906, Executor `executor_qwen` |

The apparent +22.2pp is not a valid causal uplift because seed, Executor provider and fault exposure differ. It may be cited only as a historical aggregate, never as the primary baseline comparison.

## Development Smokes

The server contains many one-episode directories (`poc_smoke_clean*`, `poc_smoke_clean_file*`, `poc_smoke_clean_writer*`, `poc_stability_v3/v4/v6/v8`, and canaries). They are useful for regression provenance but should not be pooled into an accuracy statistic because they contain repeated attempts, evolving code, task-specific debugging and selective reruns.

Notable one-task progression:

- repeated early Chrome clean smokes failed, later `poc_smoke_clean_v7` succeeded;
- file clean v2/v3 succeeded;
- Writer clean v3 succeeded after v1/v2 failed;
- these runs demonstrate bug-fix progression, not independent samples.

## Best Defensible Contribution Metrics

1. **40.9% fewer Guard calls** on the three-task clean smoke, with 3/3 success retained.
2. **4/6 controlled-fault recovery** in the best sparse fault smoke.
3. **7/21 recovery and 5/21 first-root localization** in the broader v9 fault matrix.
4. **2.8% true schema/semantic failure rate** across 354 stabilization model calls after separating policy rejection.
5. **100% UNKNOWN outcome coverage** in stabilization: 73/73 decisions have terminal resolution rows.
6. **Complete training provenance** in 4/4 canaries; 11/12 strict pass in stabilization.
7. **261 passing tests** on the current server worktree.
8. **Negative paired finding:** current natural-failure canary has -25pp paired delta, accurately revealing that replanning and verification can over-intervene.

## Claims Not Supported

- StateGuard does not currently beat Executor-only on the strict paired natural-failure canary.
- The v9 30.6% vs 8.3% aggregate is not a controlled comparison.
- Controlled-fault recovery is not comparable to UI-MOPD full OSWorld accuracy.
- Five applied replans in the paired canary did not produce a rescue.
- Evidence-source switching has not been demonstrated in the latest real batches.
- The current worktree is not yet a clean, published, reproducible GitHub revision.

## Recommended Paper Narrative

Lead with the system and observability contributions, then report controlled recovery and efficiency. Treat strict paired natural performance as an open limitation:

> StateGuard provides an explicit state-verification and intervention substrate for GUI agents. It reduces verification calls on a clean subset, recovers selected injected faults, and preserves complete provenance for decisions and outcomes. A strict four-pair natural-failure canary exposes a current net regression, showing that intervention applicability is not equivalent to task benefit and motivating evidence-aware intervention calibration.

This narrative is stronger than hiding the negative canary because it positions the work as a rigorous runtime and data framework with clearly measured remaining performance gaps.

## Next Experimental Gate

Before a 100+ rollout:

1. Fix evaluator-derived finish logging and UNKNOWN-budget precedence.
2. Make reground select a genuinely different feasible evidence source or terminate with `source_switch_unavailable`.
3. Re-run the same four strict pairs until `net_rescue >= 0` with no integrity failure.
4. Expand to 10-20 paired tasks and report bootstrap confidence intervals.
5. Only then launch 100+ paired natural-failure episodes.

## GitHub Publication State

GitHub repository: `https://github.com/KN33SOXXX/StateGuard`.

The active server branch contains uncommitted implementation. The reports have a dedicated documentation commit, but GitHub publication is blocked because the server credential is authenticated as `linhh29`, which lacks write permission to `KN33SOXXX/StateGuard`. Do not package the remaining implementation as one opaque commit. Recommended split:

1. training-ready logging and OSWorld evaluator probe;
2. UNKNOWN taxonomy, budgets and resolution lifecycle;
3. reports/configuration/tests.

Each commit should be made only after secret scanning, large-file inspection, `git diff --check`, and the full 261-test regression.
