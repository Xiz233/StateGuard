# v10 Natural Failure Rescue Design

## Research question

Given the same imperfect GUI Executor, can StateGuard complete unmodified
OSWorld tasks that Executor-only would naturally fail?

Each pair holds constant task, run seed, Executor model/prompt, DAG, frontier
guidance, action space, VM, setup, evaluator, history window and step budget.
StateGuard adds checkpoint verification, adaptive evidence, suspicion, repair,
local replan and a completion gate.

## Pair outcomes

| Baseline | StateGuard | Category |
|---|---|---|
| fail | success | RESCUED |
| success | success | PRESERVED |
| success | fail | REGRESSION |
| fail | fail | UNRESOLVED |

Primary metrics:

```text
rescue_rate = RESCUED / (RESCUED + UNRESOLVED)
regression_rate = REGRESSION / (REGRESSION + PRESERVED)
net_rescue = RESCUED - REGRESSION
paired_success_delta = (StateGuard successes - baseline successes) / pairs
```

Unknowns, contradictions, repair/replan counts, verification completeness,
steps, calls, tokens and latency are explanatory mechanism metrics.

## Fair baseline semantics

Both modes receive the same manual DAG and frontier-shaped prompt. The source
of graph progress differs:

- Executor-only records `subgoal_done` as zero-confidence `executor_claim`
  evidence so the next frontier node becomes available.
- StateGuard requires independent Guard evidence before verification.

This keeps action/planning hints aligned while isolating runtime verification.
Executor-claim evidence is never reported as independent verification.

## Canary policy

Four historical Executor-only clean failures are paired first. The canary
requires complete artifacts and no framework failures. The full run starts only
if the paired report contains at least one RESCUED case; otherwise development
returns to paired trajectory analysis.

## Data isolation

```text
/data/research/stateguard_runs/natural_failure_v10_canary_executor
/data/research/stateguard_runs/natural_failure_v10_canary_stateguard
/data/research/stateguard_runs/natural_failure_v10_executor
/data/research/stateguard_runs/natural_failure_v10_stateguard
/data/research/stateguard_runs/natural_failure_v10_pipeline
```
