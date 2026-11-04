# StateGuard Stabilization v1 Results

Date: 2026-09-21\
Branch: `feature/v10-natural-failure`\
Experiment: `osworld_stabilization_v1`\
Run directory: `/data/research/stateguard_runs/stabilization_v1`

## Executive Summary

The 12-episode mixed-task stabilization run completed. Structured-output handling and
bounded retries improved materially, all UNKNOWN decisions received hindsight resolution
records, and runaway UNKNOWN loops now terminate explicitly. However, this run is **NO-GO
for the 100+ rollout** because one successful episode is missing a finish decision, UNKNOWN
still dominates verification, evidence-source switching never occurred, and one replan path
briefly exceeded the configured consecutive-UNKNOWN budget.

The system is close to data-collection readiness, but the remaining issues are control-flow
and evidence-routing defects rather than optional model-quality improvements.

## Run Summary

| Metric | Result |
|---|---:|
| Episodes | 12 |
| Successful | 2 (16.7%) |
| `unknown_budget_exhausted` | 9 |
| `max_steps` | 1 |
| Environment steps | 185 |
| Model calls | 354 |
| Guard UNKNOWN | 73 |
| UNKNOWN rate | 79.3% |
| Logged events | 1,172 |
| Artifact manifest rows | 994 |
| Run size | 107 MB |

Task mix: 4 Calc, 3 Chrome, 3 Writer, and 2 file/terminal tasks.

## Per-Episode Outcomes

| Task | Status | Success | Steps | Guard calls | UNKNOWN types |
|---|---|---:|---:|---:|---|
| `030eeff7...` | completed | yes | 15 | 4 | none |
| `3680a5ee...` | unknown budget | no | 10 | 6 | evidence insufficient: 6 |
| `4127319a...` | unknown budget | no | 10 | 6 | evidence insufficient: 6 |
| `5ced85fc...` | unknown budget | no | 20 | 6 | evidence insufficient: 6 |
| `6f81754e...` | unknown budget | no | 14 | 8 | evidence insufficient: 7 |
| `8b1ce5f2...` | unknown budget | no | 12 | 7 | evidence insufficient: 6 |
| `99146c54...` | max steps | no | 25 | 14 | evidence insufficient: 8 |
| `aad10cd7...` | unknown budget | no | 11 | 6 | evidence insufficient: 6 |
| `66399b0d...` | unknown budget | no | 21 | 16 | evidence insufficient: 9 |
| `bc2b57f3...` | unknown budget | no | 10 | 6 | evidence insufficient: 6 |
| `c7c1e4c3...` | unknown budget | no | 12 | 7 | evidence insufficient: 6 |
| `d53ff5ee...` | completed | yes | 25 | 13 | evidence insufficient: 5; hidden/persistent: 2 |

## Improvements Confirmed

### Structured output

The old canary had 71 events labelled as parse failures, but 56 were actually runtime policy
rejections. The new logging separates these outcomes.

| Outcome | Count | Share of 354 calls |
|---|---:|---:|
| Missing-field schema failure | 6 | 1.7% |
| Invalid-value schema failure | 1 | 0.3% |
| Replanner semantic validation failure | 3 | 0.8% |
| True schema/semantic failures total | 10 | 2.8% |
| Blocked-action policy rejection | 46 | 13.0% |
| Frontier policy rejection | 3 | 0.8% |
| Domain retry intervention | 10 | 2.8% |
| Provider retry | 1 | 0.3% |

Parse retry is no longer a normal dominant path. Prompt-echo handling, smaller schemas,
normalization, and one-retry bounding are working.

### UNKNOWN resolution data

All 73 UNKNOWN events have a terminal resolution record:

- 12 `VALID` from a later state judgement;
- 2 `VALID` from the final evaluator;
- 59 `UNRESOLVED` from unsuccessful episode hindsight;
- 0 missing outcomes.

The `UNKNOWN -> evidence acquisition -> resolution` join is therefore present in the data.

### Intervention lifecycle

Every intervention has a hindsight outcome. Recorded interventions include ten domain
retries, one provider retry, and three replans. Two replans occurred in the successful
`d53ff5ee...` episode and one in a failed episode; this is not enough to infer causal uplift.

### Loop containment

Nine formerly long-running trajectories terminated explicitly with
`unknown_budget_exhausted`. The budget prevents unbounded cost and records the termination
reason instead of silently ending the episode.

## Remaining Problems

### P0: Missing finish decision on evaluator-derived success

The combined integrity check passed 11/12 episodes. `d53ff5ee...` failed because it reached
25 steps, then the final evaluator returned success and runtime changed status from
`max_steps` to `completed`. No Executor or runtime `finish_decision` event was emitted.

This is not a missing evaluator result, but it breaks the invariant that every completed
episode has an explicit completion decision. The runtime should append a finish event such
as `decision_source=evaluator_hindsight`, or preserve a distinct
`completed_by_evaluator` termination status.

### P0: UNKNOWN budget can be overridden by replan control flow

`6f81754e...` recorded `max_consecutive_unknown_observed = 7` despite a configured limit of
6. A local-replan continuation can overwrite the budget termination status for one cycle.
Budget exhaustion must take precedence over replan and be checked before any `continue`.

### P1: UNKNOWN remains the dominant failure mode

There were 73 UNKNOWN judgements and 59 remained unresolved. Nine of twelve episodes ended
because of the UNKNOWN budget. This is safe from a cost perspective but does not yet produce
sufficiently diverse natural-failure trajectories.

### P1: UNKNOWN taxonomy is insufficiently discriminative

The live run produced:

- `evidence_insufficient`: 71;
- `hidden_or_persistent_state`: 2;
- all other classes: 0.

The baseline offline classifier had identified 11 Guard-capability cases, but the live model
labelled nearly everything as evidence insufficient. Explicit model labels currently take
precedence over deterministic evidence-based inference, so the classifier may be trusting the
model too much. Cases with substantial `available_evidence` need a deterministic override or
post-hoc audit flag.

### P1: Evidence-source switching did not occur

`evidence_source_switch_count = 0` and `contract_revision_count = 0`. The system records
reground/replan infrastructure, but this batch did not demonstrate an actual switch away from
the failing evidence source. Repeating screenshot-based verification therefore remains common.

### P2: Failure diversity is low

The run produced no Guard contradictions, repair cycles, or repair actions. Most failed data is
the same pattern: insufficient evidence followed by budget exhaustion. Logging is richer, but
the collected training distribution is not yet diverse enough for a large natural-failure run.

## Integrity Check

Machine-readable report:

`/data/research/stateguard_runs/stabilization_v1/integrity_report.json`

- 11 episodes: PASS;
- 1 episode: FAIL due only to missing finish decision;
- non-finish warnings on budget/max-step episodes are expected;
- model request/response, action receipt, state boundary, artifact hash, evaluator result,
  intervention outcome, and UNKNOWN resolution joins otherwise passed.

## Go / No-Go Matrix

| Criterion | Result | Assessment |
|---|---|---|
| Raw logging has no missing joins | 11/12 pass | **NO-GO** |
| Parse retry no longer dominates | 10 true failures / 354 calls | **PASS** |
| UNKNOWN reasons are explainable | labels present but highly collapsed | **PARTIAL** |
| Consecutive UNKNOWN has a hard budget | one path reached 7 with limit 6 | **PARTIAL** |
| Diverse natural failures collected | dominated by one UNKNOWN pattern | **NO-GO** |
| Intervention outcomes traceable | all interventions closed | **PASS** |
| Evidence source can demonstrably switch | zero switches | **NO-GO** |

## Recommended Next Patch

1. Emit an explicit evaluator-derived finish event or distinct completion status.
2. Make budget termination take precedence over replan continuation.
3. Deterministically audit/override `evidence_insufficient` when available evidence is already
   substantial or a different verifier/source is required.
4. Ensure reground chooses a genuinely different feasible source, or records
   `source_switch_unavailable` and terminates without repeating equivalent contracts.
5. Run 4 targeted canaries covering successful evaluator completion, UNKNOWN budget, source
   switch, and replan. If integrity passes, repeat a 10-12 episode stabilization batch before
   starting 100+ rollout.

## Artifacts

- Summary: `/data/research/stateguard_runs/stabilization_v1/stability_report.partial.json`
- Integrity: `/data/research/stateguard_runs/stabilization_v1/integrity_report.json`
- Baseline audit: `/data/research/stateguard_runs/stabilization_v1/baseline_audit.json`
- Episode root: `/data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard/episodes`
- Run log: `/data/research/stateguard_runs/stabilization_v1/run.log`
