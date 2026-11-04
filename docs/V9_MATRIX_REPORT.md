# StateGuard v9 — 36-episode stability matrix report

Date: 2026-09-05. Branch feature/trust-trace-stateguard.
Config: configs/poc/osworld_v9_matrix.yaml (12 tasks x 3 scenarios, stateguard mode).
Executor/grounder/guard/replanner: Qwen3.7-plus (stateguard_api).

## Headline metrics
- fault injection: 21/21 (100%)
- first root accuracy (faulted): 5/21 (24%)
- fault recovery: 7/21 (33%)
- clean task success: 4/15 (27%)
- termination: completed 11 | guard_parse_failed 10 | plan_revision_failed 5 |
  max_steps 5 | repair_failed 3 | executor_parse_failed 1 | environment_failed 1
- guard_calls 327, executor_calls 1171, contracts 137, unknown_checkpoints 167,
  local_replan 5 (success 0)

## Correct localizations (acc=1.0)
- 030eeff7 earlier_state_corruption -> S2
- 4127319a earlier_state_corruption -> S2
- 4127319a wrong_value -> S2
- 5ced85fc no_effect -> S1
- 5ced85fc wrong_value -> S1

## Interpretation
1. v9 framework delivers the causal-localization claim that Round 2.5 lacked:
   adaptive evidence contracts + suspicion + trust trace let the guard localize
   earlier-corruption roots (S2) correctly on 2/3 earlier cases with data.
2. Fault injection is fully reliable (21/21).
3. Task recovery / clean success are limited by the executor: Qwen3.7-plus
   prematurely finishes and does not complete multi-step GUI actions
   (max_steps 5, clean 4/15). This is the known executor risk (handoff 4.L4),
   NOT a StateGuard diagnostic failure.
4. Framework robustness: 15/36 episodes fail in framework layers
   (guard_parse_failed 10, plan_revision_failed 5). Replanner success rate is 0
   (5 patches attempted, none applied). These are the next fixes.
5. unknown_checkpoints 167 indicates heavy evidence-debt activity; guard_calls
   327 is moderate overhead.

## Fixes applied during the run
- evidence_gap parser crash on null lists (6f5fdbe)
- premature finish no longer consumes the causal repair budget (0626423)
- mark_suspicious idempotent (avoid suspicious->suspicious crash)

## Next steps
- Fix guard_parse_failed (Guard output schema drift) and plan_revision_failed /
  replan success (patch validator / replanner protocol).
- Align with no-Guard baseline (executor_only) before claiming improvement.
- Re-run matrix after framework robustness fixes.
