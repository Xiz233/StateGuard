# StateGuard v8 Baseline

> Frozen before the v9 verifiability architecture work.

## Source

- Server: `researcher@example-host`
- Repository: `/data/research/projects/StateGuard`
- Branch: `feature/trust-trace-stateguard`
- Commit: `e654b91`
- Unit tests: `178 passed in 5.91s`
- Experiment config: `configs/poc/osworld_stability_v8.yaml`
- Experiment report: `/data/research/stateguard_runs/round3/stability_v8.json`
- Episode root: `/data/research/stateguard_runs/poc_stability_v8/osworld_stability_v8-stateguard/episodes`

## Frozen Results

| Fault case | Terminal status | Success | Steps | Executor calls | Guard calls | UNKNOWN | Suspicious | Contradictions | Repairs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14--wrong_target--2` | `plan_revision_required` | 0 | 16 | 36 | 9 | 9 | 3 | 0 | 0 |
| `bc2b57f3-686d-4ec9-87ce-edf850b7e442--no_effect--2` | `plan_revision_required` | 0 | 20 | 32 | 14 | 12 | 4 | 0 | 0 |
| `c7c1e4c3-9e92-4eba-a4b8-689953975ea4--wrong_value--1` | `max_steps` | 0 | 50 | 98 | 49 | 49 | 0 | 0 | 0 |

## Baseline Interpretation

- `infrastructure_failures=0` and the legacy `gate_passed=true` mean only that all expected result files were present and no configured infrastructure failure occurred.
- Task success is `0/3`; the baseline does not demonstrate successful recovery.
- The first two cases recognize exhausted action strategies but terminate instead of revising the plan.
- The c7 case remains on S1 for 50 actions. Guard returns UNKNOWN at 49 completion checkpoints because the structured state has no predicate or available structured evidence source.
- No v8 case reaches a useful contradiction/repair trajectory.
- The c7 injected fault is not reached, so its root and repair metrics cannot evaluate StateGuard fault recovery.

## Compatibility Gate For v9

Every v9 implementation phase must preserve:

1. The existing 178 tests.
2. Canonical action parsing, including the v8 `double_click` regression fix.
3. Separate action stagnation and node failure semantics.
4. Minimal state repair for genuine contradictions.
5. No task-id, task-description, application-name, or trajectory-specific runtime rules.

The v9 three-case run must additionally achieve:

- infrastructure failures: 0;
- terminal `plan_revision_required`: 0;
- `max_steps`: 0;
- UNKNOWN beyond configured hard debt threshold: 0;
- invalid evidence contract executing more than one step: 0;
- fault injected and exposed: 3/3;
- task success greater than the v8 baseline of 0/3;
- repair budget exhaustion: 0.
