# StateGuard v9 implementation report

## Status

The adaptive verification and runtime local-replanning path is implemented as an opt-in
extension. The previous runtime remains available when `adaptive_verification.enabled` is
false.

| Area | Status | Main files | Coverage |
|---|---|---|---|
| Stable semantic schema | Implemented | `core/schema.py`, planner/compiler | schema and round-trip regression |
| Adaptive contracts and lifecycle | Implemented | `verification/contracts.py`, `lifecycle.py` | versioning and semantic preservation |
| Capability-based grounding | Implemented | `verification/grounder.py`, environment adapter | context revision, unavailable source, five task categories |
| Contract validation | Implemented | `verification/validator.py` | weakening and unsupported route rejection |
| UNKNOWN taxonomy | Implemented | Guard parser/backend/result | parser regression and controller tests |
| Verification debt | Implemented | `runtime/verification_debt.py` | action-independent accumulation and hard limit |
| Completion suppression | Implemented | `runtime/checkpoint_policy.py` | contract/evidence/strategy signature test |
| Local DAG replan | Implemented | planning patch modules, `episode_runner.py` | valid patch, cycle, source, and protected-progress tests |
| Final invariant gate | Implemented | adaptive controller, runner | active-contract evidence and exact semantic reference |
| Trace and metrics | Implemented | trace modules, experiment logging/metrics | existing trace regression plus serialized fields |
| OSWorld experiment config | Implemented | `configs/poc/osworld_stability_v9.yaml` | YAML load check |

## Runtime behavior

Required nodes receive a capability-level feasibility preflight. Active nodes are grounded
only on explicit lifecycle triggers. UNKNOWN results accumulate debt against the semantic
goal, not an action or contract ID. Stale/unavailable measurements cause re-grounding;
exhausted measurement strategies mark the node `UNVERIFIABLE` and request a validated
minimal PlanPatch. Only exhausted or invalid replanning ends as `plan_revision_failed` in
the v9 path.

Verified nodes are passed to the patch validator as protected nodes. Their state and
evidence must remain byte-for-byte equivalent after a patch. Completion additionally
requires every required node's evidence to reference its current active contract.

## Verification

- Full server regression: `211 passed`
- Static compilation: passed
- Diff whitespace validation: passed
- No task IDs, application names, GUI coordinates, or description-keyword branches were
  added to core runtime behavior.

## Known limitations

- The final gate guarantees semantic and evidence-contract integrity, while the strongest
  environment-specific final probe still depends on the registered structured,
  persistence, accessibility, or visual verifier supplied by the adapter/Guard.
- The five-category suite is synthetic and verifies shared-core behavior. Formal OSWorld
  success-rate claims require running `osworld_stability_v9.yaml` on the experiment server.
- The model-based grounder and replanner remain probabilistic. Their output is always
  validated, but experiments are still needed to calibrate debt and retry thresholds.

The server configuration uses the existing `stateguard_api` Qwen3.7 Plus provider for
both Executor and Guard because `executor_qwen` remains an unconfigured placeholder.
