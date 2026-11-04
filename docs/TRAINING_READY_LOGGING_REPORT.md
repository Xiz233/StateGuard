# Training-Ready Logging Minimal Patch Report

Date: 2026-09-21\
Branch: `feature/v10-natural-failure`\
StateGuard: `/data/research/projects/StateGuard`

## Decision

The raw-evidence path is ready for a monitored 100+ OSWorld rollout. Legacy outputs remain intact, while the new append-only logs preserve decisions, calls, executions, state boundaries, interventions, artifacts, and evaluator details. Three real OSWorld episodes plus one deterministic fault episode passed the integrity checker.

This is a logging-readiness conclusion, not a claim that the current agent is performant: only one of three real canaries succeeded, and the two failures exhausted 30 steps after many Guard UNKNOWN responses.

## Implementation

### New training-ready layer

- `stateguard/training_logging.py`
  - `TrainingReadyLogger`: writes `events.jsonl`, `model_calls.jsonl`, `artifact_manifest.jsonl`, `interventions.jsonl`, and `evaluator_result.json`.
  - `RecordingModelClient`: wraps Executor, Guard, Grounder, and Replanner calls.
  - Requests are written before entering the provider call; terminal response/failure is appended later.
  - Domain retries link `retry_of_call_id` and `retry_intervention_id`; provider attempts have stable attempt IDs and reconstructable request deltas.
- `scripts/check_training_ready_episode.py`
  - Checks event closure, model request/terminal records, execution receipts, state boundaries, artifact references/files/SHA256/size, UNKNOWN continuation, finish, and evaluator details.

### Runtime integration

- `experiments/poc/runner.py`: creates the episode logger before clients and wraps all four model roles when `evaluation.save_model_responses` is enabled.
- `experiments/poc/logging.py`: dual-writes new evidence beside legacy trajectory/guard/repair logs and uses hard links for duplicate screenshot storage where possible.
- `stateguard/runtime/episode_runner.py`: logs Executor decisions, finish, parse/model failures, environment exceptions, evaluator lifecycle, replan/repair/reground interventions, and before/after state.
- `integrations/osworld/adapter.py`: records action execution receipts and probes final evaluator components.
- `stateguard/models/{openai_compatible,openai_responses,anthropic_compatible}.py`: preserves provider retry attempts, failures, latency, and request deltas.
- `stateguard/{executor/mllm_executor,guard/backends/mllm_backend,verification/grounder,planning/runtime_replanner}.py`: attaches domain parse results/errors to the originating call.

### Validation assets

- `tests/test_training_ready_logging.py`
- `configs/poc/osworld_training_logging_canary.yaml`
- `scripts/audit_osworld_evaluator.py`
- `docs/OSWORLD_EVALUATOR_AUDIT.md`

## Eight Requirements

| Requirement | Status | Evidence |
|---|---|---|
| 1. Append-only logical events | COMPLETE | Actions, finish, failures, retries, evaluator, interventions, and environment exceptions are represented in `events.jsonl` or linked append-only call/intervention logs. |
| 2. All four model-call roles | COMPLETE | Exact caller messages/schema, image artifact IDs, raw/parsed response, parse updates, error, provider/model, latency, usage, and attempts are saved. |
| 3. Action receipt | COMPLETE | Proposed/parsed/backend action, success, exception, duration, and raw environment metadata are stored on every transition. |
| 4. Full evaluator result | COMPLETE | Score, success, `EvaluationResult.details`, component probe output, and evaluator exception are persisted. |
| 5. Artifact manifest | COMPLETE | Content-addressed path, SHA256, role, dimensions, size, MIME type, source, and producer ID are saved. |
| 6. State boundaries | COMPLETE | Logical decision/transition/evaluator/intervention events include before, after, and normalized delta. |
| 7. Intervention lifecycle | COMPLETE | Decision, execution, immediate result, and episode hindsight outcome share a stable intervention ID for retry/reground/replan/repair. |
| 8. `save_model_responses` connected | COMPLETE | Executor, Guard, Grounder, and Replanner all produced non-empty records in real canaries when invoked. |

## Canary Results

Real output root:

`/data/research/stateguard_runs/training_logging_v1_canary/osworld_training_logging_canary-stateguard/episodes`

| Episode | Outcome | Coverage |
|---|---|---|
| `030eeff7...--seed-20260921` | success, score 1.0 | 14 transitions, normal GUI actions, 25 calls, four parse failures, finish, evaluator PASS |
| `3680a5ee...--seed-20260921` | max steps, score 0.0 | 30 transitions, 19 UNKNOWN, two replans, 81 calls, two evaluator conditions |
| `4127319a...--seed-20260921` | max steps, score 0.0 | 30 transitions, 18 UNKNOWN, one replan, 77 calls, terminal-output evaluator condition |
| `fake_wrong_target--stateguard--fake_wrong_target` | recovered, score 1.0 | injected contradiction, repair request/execution, finish, evaluator PASS |

The three real episodes used 60 MB total, roughly 20 MB per episode. `/data/research` had about 4.3 TB free during validation.

## Integrity Result

Combined report:

`/data/research/stateguard_runs/training_logging_v1_canary/integrity_report.json`

- Result: PASS for all four episodes; no integrity errors.
- 163 logical events, 186 model calls, 77 environment transitions, and 450 manifest records were checked.
- Every referenced artifact existed and matched its recorded SHA256 and byte size.
- All 37 real UNKNOWN events had later traceable events.
- Two max-step episodes correctly have no finish proposal; the successful real and controlled-fault episodes both preserve finish decisions.
- The latest controlled-fault run additionally verified pre-call `call_started` records, matching terminal call records, intervention events, and state-bearing model-call events.
- Regression suite: `256 passed`.

## Remaining Limits

- Agent quality remains the dominant issue: real success was 1/3, UNKNOWN rate was high, and model parse failures caused long episodes. Logging now exposes these failures but does not solve them.
- Final evaluator component probes repeat getters/metrics and can add seconds to tens of seconds. They remain final-only by default.
- Missing output files are sometimes returned by OSWorld getters as `null` rather than exceptions.
- Top-level evaluator conditions are available, but nested cell/paragraph/rule diffs and causal failure localization are not.
- The three real episodes began before the final pre-call/state-link tightening was loaded into their Python process. The final implementation was separately exercised by the controlled-fault canary and the full test suite.

## Rollout Recommendation

Proceed with 100+ episodes, keeping `training_ready_logging: true` and `save_model_responses: true`. Monitor provider latency/error rate and disk growth during the first 10 episodes. No additional logging architecture change is required before starting; performance and Guard-policy tuning should be treated as separate work.
