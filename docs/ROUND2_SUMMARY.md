# StateGuard — Auto-DAG + Frontier + Sparse Verification (Round 2)

## 1. Modified / new files
New:
- `stateguard/planning/{__init__,auto_dag,parser,prompts}.py` — Auto-DAG generator
- `stateguard/runtime/checkpoint_policy.py` — sparse checkpoint scheduler
- `tests/test_auto_dag_sparse.py` (19 tests)
- `scripts/generate_auto_dag_audit.py`, `scripts/compare_smoke.py`
- `configs/poc/osworld_sparse_smoke_{a,b,c}.yaml`, `osworld_sparse_fault_smoke.yaml`,
  `selected_tasks_sparse_smoke.yaml`

Modified:
- `stateguard/core/schema.py` — ActionProposal.subgoal_done
- `stateguard/core/dependency_graph.py` — executable_frontier
- `stateguard/executor/parser.py` — subgoal_done (default false)
- `stateguard/executor/mllm_executor.py` — guidance=frontier, subgoal_done contract,
  frontier enforcement
- `stateguard/runtime/episode_runner.py` — sparse mode, UNKNOWN rewrite, metrics
- `experiments/poc/runner.py` — config plumbing, auto-DAG provider, dag metrics
- `experiments/poc/logging.py` — dag/checkpoint metrics

## 2. Architecture
User Task -> Initial Obs -> Auto-DAG (optional) -> VerifiedTaskState
  -> executable_frontier -> Executor (atomic actions) -> OSWorld
  -> only at checkpoint -> StateGuard (VERIFIED/UNKNOWN/CONTRADICTED)
Guard decides WHAT states become true; Executor decides HOW; Guard verifies
STATE TRANSITIONS, not every atomic action.

## 3. Auto-DAG prompt (stateguard/planning/prompts.py)
Generates semantic STATES (2-8 nodes), not GUI actions; no coordinates;
persistence nodes required; no hidden runtime fields; S1..Sn topological ids.

## 4. Auto-DAG schema
{"nodes":[{node_id, description, dependencies, expected_result_semantic,
evidence_mode(visual|structured|persistence|hybrid), required}]}

## 5. Sparse checkpoint rules
Guard only on: subgoal_done, finish, repair_revalidation, stagnation
(repeated action >=3 OR same-subgoal >=10 consecutive steps).
Fault exposure is never a trigger. UNKNOWN != failure/repair/re-query.

## 6. pytest
142 passed (0 failures).

## 7. 12-task Auto-DAG audit
All 12 VALID (first attempt). /data/research/stateguard_runs/auto_dag_audit/

## 8. A/B/C clean smoke comparison
| cfg | task | succ | env | steps | guard_calls | termination |
|---|---|---|---|---|---|---|
| A | Chrome/File/Writer | 3/3 | 1.0 | 9/5/11 | 8/4/10 | completed |
| B | Chrome/File/Writer | 3/3 | 1.0 | 12/50/22 | 5/1/7 | comp/comp/exec_parse |
| C | Chrome/File/Writer | 2/3 | 0/1.0/1.0 | 44/50/50 | 7/12/16 | exec_parse/comp/comp |

Total guard calls: A=22, B=13 (40.9% reduction), C=35.
Clean success: A=3/3, B=3/3, C=2/3.

Gates: G1 PASS (40.9% reduction), G2 PASS (B=3/3>=A), G3 PASS (no
UNKNOWN-loop termination), G4 PASS (auto-DAG valid).

## 9. Guard calls / success / termination comparison
- B (manual+sparse): 13 guard calls vs A 22 (41% less), 3/3 success.
- No verification_failed / repair_failed / UNKNOWN-loop terminations in any config.
- 2 executor_parse_failed statuses are executor output-quality issues (1 still
  succeeded, env=1.0), not Guard problems.

## 10. Discovered failure cases
- Original stagnation detector only caught identical actions; executor wandering
  (varied actions, 46/50 steps on one subgoal) bypassed it. Fixed with a
  same-subgoal consecutive-step trigger (max_actions_per_subgoal=10).
- B File: executor repeatedly proposes premature finish (44 checkpoints); guard
  rejects each with zero model cost (rule-based verify_finish).
- C Chrome: failed (env=0) — auto-DAG + sparse could not recover Chrome.

## 11. Fault smoke (Phase 14) — B config, manual DAG + sparse
| task | scenario | succ | env | root | acc | status |
|---|---|---|---|---|---|---|
| Chrome | earlier | True | 1.0 | - | 0.0 | completed |
| Chrome | wrong_target | True | 1.0 | - | 0.0 | completed |
| File | no_effect | True | 1.0 | - | 0.0 | completed |
| File | wrong_value | False | 0.0 | S1 | 1.0 | repair_failed |
| Writer | earlier | False | 0.0 | S4 | 0.0 | repair_failed |
| Writer | wrong_target | True | 1.0 | - | 0.0 | completed |

Findings:
- Fault injection 100% valid.
- Localization 1/6 correct (File wrong_value -> S1). Chrome faults missed (executor
  self-corrected before a checkpoint). Writer earlier localized S4 (first downstream
  contradiction) not S3 (true root).
- Recovery 4/6 (2 repair_failed: File wrong_value, Writer earlier).
- Causal mechanism works when a contradiction is observed at a checkpoint; sparse
  reduces Guard calls AND some localization capability.

## 12. Recommendation: REVISE
Clean gates all PASS (over-intervention solved, 41% guard reduction, no premature
termination). Fault smoke shows sparse trades away some causal-localization:
a hybrid is needed (sparse by default + targeted verification of high-risk
persistence/effect nodes, and more aggressive stagnation handling).

## Commit
feature/auto-dag-sparse: df41191 (implementation); this round adds stagnation
improvement + smoke configs + summary.
