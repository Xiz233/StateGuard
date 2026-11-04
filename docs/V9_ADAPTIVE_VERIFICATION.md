# StateGuard v9 adaptive verification

StateGuard v9 keeps task semantics stable while adapting evidence collection to the
current environment. It does not add task-, application-, or benchmark-specific rules.

## Architecture and schema

`SemanticGoal` is the immutable task-state invariant. `VerificationIntent` describes the
kind of proof desired without predicting future UI details. A versioned
`AdaptiveEvidenceContract` contains observable claims, current UI anchors, evidence
sources and verifier choices. Contract status is maintained separately from task-node
status, and every accepted revision remains in `ContractStore` history.

## Runtime flow

1. The planner emits an immutable `SemanticGoal` and a source-neutral
   `VerificationIntent` for each DAG node.
2. `VerificationGrounder` binds that intent to currently available evidence and creates
   a versioned `AdaptiveEvidenceContract`.
3. `validate_contract` rejects semantic changes, weaker claims, unavailable evidence,
   and unsupported verifiers before a contract becomes active.
4. StateGuard classifies inconclusive checks with the `UnknownReason` taxonomy and a
   structured evidence gap.
5. `VerificationDebtTracker` accumulates debt by node and semantic goal, so changing an
   action or contract ID cannot reset convergence limits.
6. The controller escalates from suspicion to contract re-grounding, verifier strategy
   switching, and finally `UNVERIFIABLE`.
7. `RuntimeReplanner` replaces only the smallest unverifiable DAG region. Verified nodes
   are protected by the patch validator and remain intact.
8. Repeated completion claims are suppressed until the contract, evidence signature, or
   strategy changes. Final completion requires evidence from each node's active contract
   and exact preservation of its semantic invariant.

## Lifecycle and recovery

Grounding is limited to node activation, context shifts, stale contracts, source failure,
repeated UNKNOWN, repair revalidation and local replan boundaries. Stable app, window,
page and modal identity drive context changes; screenshot hashes are not used.

UNKNOWN is classified as `need_more_evidence`, `contract_stale`, `source_unavailable`,
`verifier_inconclusive`, or `node_unverifiable`. These respectively continue evidence
acquisition, re-ground the contract, choose an alternate source, switch strategy, or
request a local DAG patch. Contradictions continue through the existing causal
localization and minimal state-repair path.

## Environment and generalization

Adapters expose `EnvironmentCapabilities` and build an `ObservationBundle`; accessibility
is optional. Runtime decisions use resolved capabilities instead of executor-declared
observability. The core contains no task IDs, app names, description keywords or fixed UI
coordinates. Five synthetic task categories exercise the same grounding and validation
path.

## Configuration

The feature is opt-in under `adaptive_verification`. A complete OSWorld configuration is
available at `configs/poc/osworld_stability_v9.yaml`. Setting `enabled: false` preserves
the previous runtime path.

Important budgets are `max_grounding_attempts`, the limits under
`runtime_replanning`, and the three ordered thresholds under `verification_debt`.
The adaptive contract, debt, local replanning, and completion-suppression switches are
separate so the experiment runner can execute ablations without changing core code.

## Artifacts and metrics

Each episode records the active contract and verification debt in
`execution_trace.jsonl`, contract lifecycle changes in `contract_events.jsonl`, and local
DAG edits in `plan_patch_events.jsonl`. Episode and run summaries include contract
generation/revision failures, semantic weakening rejections, source switches,
unverifiable nodes, debt triggers, local replan outcomes, and executor overclaims.

The regression suite covers semantic weakening, unavailable evidence/verifiers, context
revision, contract-stale recovery, semantic-level debt, completion suppression, invalid
patches, verified-progress preservation, final-contract evidence and five task categories.
