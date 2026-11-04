# StateGuard Round 2.5 — Hybrid Verification (in progress)

## 1. Modified / new files
New:
- `stateguard/runtime/checkpoint_policy.py` (rewritten) — unified CheckpointPolicy
  (dense/sparse/hybrid), CheckpointDecision(should_verify, reason, target_node,
  checkpoint_kind), NodeRisk + compute_node_risk
- `configs/poc/osworld_sparse_smoke_h.yaml`, `osworld_hybrid_fault_smoke.yaml`
- `scripts/replay_earlier_root.py`, `scripts/replay_earlier_batch.py`
- `round2_5/` baseline metadata, forensic, replay reports

Modified:
- `stateguard/runtime/episode_runner.py` — unified evaluate() entry, causal
  candidate chain, checkpoint_kinds, premature_finish_count + rule-based
  premature-finish feedback
- `stateguard/guard/backends/mllm_backend.py` — causal_chain + checkpoint_kind
  prompt, consistency_policy, causal_policy, fault_root restricted to candidate
- `stateguard/guard/state_guard.py` — passes checkpoint_kind/candidate_nodes;
  consistency checkpoints fail-open on the in-progress active node
- `stateguard/guard/backends/hybrid_backend.py` — pass-through new args
- `experiments/poc/runner.py` — hybrid config plumbing, certified_clean on clean
- `experiments/poc/logging.py` — checkpoint_kinds, premature_finish_count

## 2. Hybrid checkpoint architecture
```
env.step() -> CheckpointPolicy.evaluate(proposal, task_state, graph, obs, ...)
   -> CheckpointDecision(should_verify, reason, target_node, checkpoint_kind)
   -> only if should_verify -> StateGuard.verify_transition(...)
   -> VERIFIED / UNKNOWN (fail-open) / CONTRADICTED (deterministic invalidation)
```
Three layers: A) mandatory (subgoal_done/finish/repair_revalidation/stagnation);
B) causal-risk proactive (HIGH every 2, MEDIUM every 5 env actions, LOW none);
C) cooldown (2 env actions) before another periodic check on the same node.

## 3. NodeRisk (deterministic)
compute_node_risk(node, graph): persistence evidence_mode -> HIGH; >=2
descendants -> HIGH; 1 descendant -> MEDIUM; leaf -> LOW. Causal leverage =
how much downstream progress a wrong state would pollute.

## 4. Checkpoint reasons / kinds
- subgoal_done (completion), finish (finish), repair_revalidation (repair),
  stagnation (consistency), causal_risk (consistency)
- fault exposure is never a trigger.

## 5. Guard causal-context prompt
- causal_chain: ancestors(active)+[active] compact state summaries (topo order)
- consistency_policy: active subgoal need NOT be complete; CONTRADICTED only on
  positive evidence of state corruption, else UNKNOWN
- causal_policy: visibility point != causal root; trace backward to EARLIEST
  corruption; fault_root must be in causal_chain

## 6. pytest: 149 passed (0 failures)

## 7-8. A/B/H clean smoke (3 tasks)
| cfg | Chrome gc | File gc | Writer gc | total | success |
|---|---|---|---|---|---|
| A dense | 8 | 4 | 10 | 22 | 3/3 |
| B sparse | 5 | 1 | 7 | 13 | 3/3 |
| H hybrid | 4 | 2 | 7 | 13 | 3/3 (all env=1.0) |
Gate B (overhead <= 0.65*dense=14.3): PASS (13). Gate E (success >= sparse): PASS.

## 9. Findings
- Hybrid keeps guard calls at sparse level (41% below dense) while clean success
  is maintained -> over-intervention solved.
- H Writer quirk: repair_failed status despite env=1.0 caused by consistency
  checkpoints judging in-progress node as CONTRADICTED (4 false repairs) -> FIXED
  (consistency checkpoints now fail-open on active node).

## 10. Earlier-root replay (phase-11)
new-prompt First Root Accuracy (earlier): 1/6 (030eeff7 only). 3680a5ee/8b1ce5f2
no contradiction observed; 4127319a/99146c54/d53ff5ee predict downstream/None.
Conclusion: causal-context prompt alone does not recover earliest-root
localization. Per phase-11.3 (<4/6) -> REVISE, do NOT run 108 yet.

## 11. File WRONG_VALUE forensic
Diagnosis correct (S1, acc=1.0) but repair failed: 34 repair actions, 4 cycles
exceeded per-fault budget; executor could not rewrite output.txt.

## 12. Recommendation (pending hybrid fault smoke)
Likely REVISE for the causal-localization claim (1/6). Hybrid overhead + clean
gates PASS. Recovery data pending fault smoke.
