# StateGuard v10 Code Audit

## Scope

- Repository: `/data/research/projects/StateGuard`
- Branch: `feature/v10-natural-failure`
- Audited surface: runtime state transitions, repair/replan lifecycle, adaptive
  verification, experiment resume/reporting, model failure handling, and OSWorld
  resource cleanup.
- Verification: full server test suite plus Python compilation and shell syntax checks.

## Fixed defects

### 1. Active repair retained a removed DAG node

After replacing `S1R` with `S1R-P`, `active_repair.fault_root` still referred to
`S1R`. The next repair phase called `task_state.get("S1R")` and crashed.

Fixes:

- `stateguard/core/schema.py`: `RepairRequest.remap_nodes()` maps and validates all
  live repair node references.
- `stateguard/runtime/episode_runner.py`: a plan patch is staged and repair mapping
  is validated before the new task state is committed.
- `stateguard/runtime/repair_loop.py`: consumed repair budgets follow the replacement
  root, preventing node renaming from resetting limits.

### 2. Replan left stale runtime identity caches

Checkpoint history, completion claims, evidence contracts, verification debt,
replan counters, repair target sets, and injected-root tracking could retain IDs
that no longer existed in the patched graph. This could cause crashes, ineffective
limits, and inaccurate intervention metrics.

Fixes:

- `stateguard/runtime/checkpoint_policy.py`: discard removed-node scheduler state.
- `stateguard/verification/lifecycle.py`: retire removed-node contracts.
- `stateguard/runtime/verification_debt.py`: carry attempted evidence strategies to
  the replacement while resetting convergence counters.
- `stateguard/runtime/adaptive_verification.py`: reconcile contract/debt state on a
  plan patch.
- `stateguard/runtime/episode_runner.py`: remap all live ID sets and transfer the
  per-node replan count.

### 3. Task-state updates were not atomic

A multi-operation Guard update could mutate early nodes and then fail on a later
invalid operation, leaving a partially applied state.

Fix:

- `stateguard/core/task_state.py`: validate and apply updates to a shadow copy before
  committing the node map.

### 4. Model/API failures aborted the experiment process

Executor failures were classified, but Guard finish calls, Guard transition calls,
adaptive grounding, and final invariant verification could still escape as uncaught
exceptions. This lost the episode result and stopped the long-running pipeline.

Fix:

- `stateguard/runtime/episode_runner.py`: classify these failures as `model_failed`,
  retain the error, evaluate the environment, and write a normal result artifact.

### 5. OSWorld environments leaked on exceptional exits

`env.close()` ran only after a successful episode. Any uncaught runtime or logging
exception could leave the VM/backend alive.

Fix:

- `experiments/poc/runner.py`: environment closure now runs in `finally`.

### 6. Resume semantics could bias paired experiments

The v10 pipeline used `--resume --rerun-failed`, which treated valid benchmark
failures such as `max_steps` as infrastructure failures. Restarting the pipeline
therefore reran one side of an existing pair and wasted substantial time.

Fixes:

- `scripts/run_v10_natural_pipeline.sh`: normal recovery uses `--resume` and keeps
  every complete result, regardless of task success.
- `experiments/poc/runner.py`: corrupt/non-object `result.json` files are not treated
  as resumable results; their episode directory is archived and rerun.

## Remaining operational risks

- External model availability and OSWorld reset failures can still stop a canary.
  Completed results remain resumable, and completeness checks reject framework
  failures before reporting.
- The repository does not install `ruff`; linting was limited to compilation,
  targeted static searches, `bash -n`, and the test suite.
- The canary gate intentionally requires at least one natural-failure rescue before
  launching the 12-pair experiment. A no-rescue result is an experimental outcome,
  not a framework crash, and requires trajectory analysis before scaling.

## Verification record

- Commit `8a418bd`: repair/replan state reconciliation.
- Commit `2f84998`: model failure handling, cleanup, and v10 resume policy.
- Commit `91384c7`: runtime identity metrics and corrupt-result recovery.
- Server test result after the fixes: `247 passed`.
