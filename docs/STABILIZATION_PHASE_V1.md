# StateGuard Stabilization Phase v1

Date: 2026-09-21\
Branch: `feature/v10-natural-failure`

## Baseline Diagnosis

Source: three training-logging canaries, 183 model calls.

- UNKNOWN: 37 total.
- `evidence_insufficient`: 26 (70.3%).
- `guard_capability_insufficient`: 11 (29.7%).
- Other taxonomy classes: 0 in this small baseline.
- Formerly reported parse failures: 71 total.
- True missing-field schema failures: 12 (16.9%).
- Blocked-action policy rejection: 55 (77.5%).
- Frontier policy rejection: 1 (1.4%).
- Replanner semantic validation: 3 (4.2%).

The old metric conflated parser/schema failures with deliberate runtime-policy rejection.
The baseline machine-readable audit is:

`/data/research/stateguard_runs/stabilization_v1/baseline_audit.json`

## Implemented Stabilizers

### UNKNOWN taxonomy and routing

`stateguard/verification/unknowns.py` defines:

- `evidence_insufficient`
- `verification_target_unclear`
- `hidden_or_persistent_state`
- `contract_unverifiable`
- `guard_capability_insufficient`
- `environment_state_missing`

Guard output now includes `unknown_type`. Missing or invalid model labels are inferred from
the structured evidence gap, reason, target, and source availability. Existing but underused
evidence is routed to verifier or strategy switching; hidden or unavailable state is routed to
new-source grounding instead of another identical screenshot judgement.

### Structured output

- Executor and Guard use smaller response schemas.
- Executor parser normalizes conservative wrappers and common field aliases.
- Prompt-echo responses no longer get copied into an ever-growing retry conversation.
- Parse/schema failure, policy rejection, and deterministic fallback have separate statuses
  and `failure_type` values.
- Stabilization runs permit one correction retry per call.

### Budgets

The stabilization configuration enforces:

```text
max_parse_retry_per_call = 1
max_consecutive_unknown = 6
max_reground_per_node = 2
max_replans_per_node = 2
max_repair_cycles = 3
max_total_guard_calls = 20
max_total_steps = 25
```

Budget termination is explicit (`unknown_budget_exhausted`, `guard_budget_exhausted`,
repair/replan status) and is written as an `episode_termination` event.

### UNKNOWN resolution chain

`unknown_resolutions.jsonl` is append-only. Each UNKNOWN first receives a PENDING record,
then a stable-ID outcome:

```text
VALID      <- later verified state or successful final evaluator
FAILED     <- later contradiction
UNRESOLVED <- unsuccessful final hindsight with no stronger later judgement
```

Each outcome carries resolution step, evidence references, and source (`later_state`,
`evaluator`, or `hindsight`).

## Stabilization Run

Configuration: `configs/poc/osworld_stabilization_v1.yaml`\
Episodes: 12 mixed OSWorld tasks\
Output: `/data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard`\
Log: `/data/research/stateguard_runs/stabilization_v1/run.log`\
PID: `/data/research/stateguard_runs/stabilization_v1/run.pid`

Analyze completed episodes with:

```bash
.venv-stateguard/bin/python scripts/analyze_stabilization.py \
  /data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard/episodes \
  --output /data/research/stateguard_runs/stabilization_v1/stability_report.json
```

Run the per-episode integrity checker before the Go/No-Go decision.

## Go / No-Go

GO requires:

- no integrity errors or missing request/response/action/artifact/evaluator joins;
- true parse retries are a minority of calls and materially below baseline;
- every UNKNOWN has a standardized type and terminal resolution row;
- no episode exceeds consecutive-UNKNOWN, reground, replan, repair, or Guard-call budgets;
- interventions have hindsight outcomes;
- the batch contains more than one natural failure pattern.

Final task success and proven Replan uplift are not gates for logging rollout readiness.

## Initial Live Validation

The first real episode (`030eeff7...`) completed successfully in 15 steps with score 1.0.
Its integrity check passed without errors or warnings:

- 23 model calls, 14 environment transitions, 70 artifact records;
- one true missing-field schema failure, followed by one bounded retry;
- one separately classified frontier policy rejection;
- no UNKNOWN loop;
- finish and evaluator component details present;
- every intervention has a hindsight outcome.

The remaining mixed-task episodes continue in the background.
