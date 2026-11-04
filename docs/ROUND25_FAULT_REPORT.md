# Hybrid fault smoke (phase-21/23) — final comparison

## Sparse fault smoke (earlier) vs Hybrid fault smoke

| task | scenario | Sparse succ | Sparse root | Hybrid succ | Hybrid root |
|---|---|---|---|---|---|
| Chrome | earlier | 1.0 | None | 1.0 | None |
| Chrome | wrong_target | 1.0 | None | 1.0 | None |
| File | no_effect | 1.0 | None | 1.0 | None |
| File | wrong_value | 0.0 | S1 (acc 1.0) | 0.0 | None |
| Writer | earlier | 0.0 | S4 (acc 0) | 0.0 | None |
| Writer | wrong_target | 1.0 | None | 0.0 | None |

Fault recovery:  Sparse 4/6,  Hybrid 3/6
Localization:    Sparse 2/6,  Hybrid 0/6
Guard calls (clean): both 13 (41% below dense)

## Gates (phase-23)
- Gate A fault validity: PASS (100% injected both)
- Gate B overhead: PASS (13 <= 0.65*22=14.3)
- Gate C causal localization > sparse: FAIL (0/6 vs 2/6; earlier replay 1/6)
- Gate D recovery >= sparse: FAIL (3/6 vs 4/6)
- Gate E clean >= sparse: PASS (3/3)
- Gate F runtime health: no verification_failed, but hybrid suppressed all
  consistency contradictions (fail-open) -> lost detection

## Root cause
The consistency fail-open fix (needed to stop false contradictions on
in-progress nodes, which caused repair_failed-with-env-1.0) ALSO suppresses
legitimate active-node contradictions at causal-risk checkpoints. In hybrid,
no repairs arise from consistency checkpoints, so File wrong_value and Writer
wrong_target are never localized/repaired. Fail-open is too blunt.

## Recommendation
REVISE (do NOT run Round-3 108).
Next iteration: replace blunt fail-open with suspicion-then-confirm — mark the
active node as suspect on a consistency contradiction, confirm at the next
completion checkpoint (subgoal_done) before committing to repair. And add
per-candidate expected-state checks to recover earliest-root localization
(target >= 4/6 on the earlier replay).
