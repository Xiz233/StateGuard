# StateGuard v9 Implementation Plan

## Objective

Make StateGuard distinguish two independent failure classes and recover from both:

```text
world state contradiction -> causal localization -> minimal state repair
plan/verifier deficiency  -> verification debt -> validated local DAG replan
```

Runtime behavior must depend only on generic task nodes, evidence contracts, environment capabilities, evidence results, traces, debt state, and graph patches.

## Engineering Rules

1. No checks for task IDs, description keywords, application names, professor semantics, or known trajectories.
2. Executor-declared observability is advisory and must never control runtime verification.
3. Repeated UNKNOWN must not be converted to FAILED without contradictory evidence.
4. A new task may add only task/fault configuration; it must not require changes to core runtime.
5. Every LLM-created DAG or patch is validated before it can mutate live state.
6. Existing state repair remains separate from plan repair.
7. Each phase must pass the existing suite plus its new tests before the next phase begins.

## Delivery Sequence

### v9-00: Freeze v8

Deliver `docs/V8_BASELINE.md` with commit, tests, config, paths, per-case results, and compatibility gates.

### v9-01: Evidence Contract Schema

Add `stateguard/verification/contracts.py`:

- `EvidenceType`
- `EvidenceSource`
- immutable/serializable `EvidenceContract`

Extend `TaskNode` with optional `evidence_contract` while preserving legacy task JSON loading. Implement a deterministic legacy adapter so existing `evidence_mode`, `structured_predicate`, `expected_effect`, and `verify_action` remain readable during migration.

Tests:

- contract JSON round trip;
- TaskNode legacy round trip;
- no mutation aliasing for source/field collections.

### v9-02: Environment Capability Registry

Add `stateguard/environment/capabilities.py`:

- `EnvironmentCapabilities`
- available evidence sources;
- supported verifier IDs;
- action-to-source effect channels;
- capability query helpers.

Adapters expose capabilities with a conservative fallback of screenshot-only. No core component assumes accessibility is available.

Tests:

- screenshot-only environment;
- structured environment;
- optional accessibility;
- unsupported verifier/source rejection.

### v9-03: Contract Preflight

Add `stateguard/verification/validator.py`:

- `InvalidContract`
- `ContractValidationResult`
- `validate_task_graph`

Validate every required node for contract existence, source availability, verifier registration, success condition, structured predicate/tool, and persistence verifier/action. Validation uses capabilities, never description keywords.

Initial runtime mode is report-only behind config until local replanning exists, so this phase cannot strand existing tasks.

Tests use unrelated visual, setting, persistence, and unverifiable synthetic nodes.

### v9-04: Observation Bundle And Verifier Registry

Add:

- `verification/observation.py`
- `verification/result.py`
- `verification/registry.py`

Implement the common verifier protocol and first-party verifiers:

- structured predicate;
- accessibility predicate;
- persistence callback/action contract;
- visual MLLM adapter.

Migrate HybridBackend incrementally: registry first, legacy Rule/MLLM fallback second. This keeps behavior stable while contracts are migrated.

### v9-05: Resolved Observability

Add `core/observability.py::CapabilityResolver`.

Inputs:

- action;
- active node contract;
- environment capabilities;
- verifier registry.

Outputs:

- usable sources;
- verifier candidates;
- direct-observability flag;
- resolution reason.

Keep `proposal.effect_observability` for compatibility and logging, expose it as declared observability, and record both declared and resolved values in trace.

Required test: an Executor claiming `structured` in a screenshot-only environment cannot make runtime resolve structured observability.

### v9-06: Evidence Signatures And Verification Debt

Add:

- `verification/evidence_signature.py`
- `runtime/verification_debt.py`

Debt key is `(node_id, contract_id)`, never action. Track consecutive UNKNOWN, no-information-gain count, repeated target, attempted verifiers/strategy classes, last evidence signature, and last progress step.

Configurable states:

- soft threshold: suspicion signal;
- strategy threshold: force evidence strategy switch;
- hard threshold: mark plan path unverifiable.

Debt clears only on VERIFIED, CONTRADICTED, or contract-relevant information gain. Changing GUI actions alone does not clear it.

### v9-07: UNVERIFIABLE And Suspicion Reasons

Extend schema/state machine with `NodeStatus.UNVERIFIABLE` and typed `SuspicionReason` values:

- weak contradiction;
- verification stagnation;
- evidence conflict;
- executor overclaim;
- state drift.

UNVERIFIABLE means the current evidence/plan contract cannot establish truth. It does not propagate FAILED/STALE and does not start state repair.

### v9-08: Structured Evidence Gap

Extend Guard output with backward-compatible `EvidenceGap`:

- missing/available/unavailable evidence;
- attempted and recommended strategy class;
- requires-new-source flag;
- same-contract flag.

Strategy classes remain state-level: acquire visual, accessibility, structured or persistence evidence; navigate to observable state; external state query.

### v9-09: PlanPatch And Validation

Add:

- `planning/plan_patch.py`
- `planning/patch_validator.py`

Validation is performed on cloned DAG/state and checks acyclicity, dependencies, IDs, evidence contracts, capabilities/verifiers, replacement anchor, downstream connectivity, protected VERIFIED nodes, and orphan nodes. Invalid patches cannot mutate live state.

### v9-10: Runtime Local Replanner

Add `planning/runtime_replanner.py` with a provider protocol plus MLLM implementation. Input is a bounded local context: task goal, problem node, boundary ancestors/descendants, current observation bundle, existing contract, debt/strategy summary, relevant trace summary, and protected VERIFIED nodes.

Apply valid patches atomically. Preserve unrelated VERIFIED nodes and evidence. Replace only the problematic local region and reconnect downstream boundary nodes through the replacement anchor.

### v9-11: Episode Integration

Integrate, in order:

1. resolve environment capabilities;
2. preflight contracts;
3. collect observation bundles;
4. resolve observability independently of Executor claims;
5. update evidence/debt after Guard result;
6. request strategy switch at configured threshold;
7. mark UNVERIFIABLE at hard threshold;
8. request, validate, and apply local patch;
9. continue the same episode.

`plan_revision_required` becomes an internal runtime event. Only exhausted patch attempts/budgets may terminate as `plan_revision_failed`.

### v9-12: Completion Claim Suppression

Track completion claims per node and last checked evidence signature. The first `subgoal_done` remains mandatory. Repeated claims without information gain or a new verifier strategy do not trigger another Guard call and add `EXECUTOR_OVERCLAIM` suspicion/debt instead.

### v9-13: Trace Analyzer

Add `trace/analyzer.py::NodeTraceSummary` with actions, claims, verdicts, evidence sources/strategies, no-gain steps, debt, and last progress. Pass summaries only at suspicion, hard checkpoints, contradictions, and replans.

### v9-14: Optional OSWorld Accessibility

Expose accessibility data in ObservationBundle when OSWorld provides it. Advertise the source only when collection succeeds. Screenshot fallback remains valid and core behavior remains benchmark-independent.

### v9-15: Metrics And Gates

Separate:

- infrastructure gate;
- contract gate;
- behavior gate;
- task success;
- injection/exposure/detection conditional metrics;
- root correctness given detection;
- repair attempted/succeeded given detection;
- replan counts/success;
- debt triggers;
- calls, tokens, and latency;
- declared/resolved observability mismatch rate.

### v9-16: Synthetic Generalization Suite

Cover browser navigation, application settings, persistence, document editing, and form/data entry using configuration/contracts only. Core source must not change to add these cases.

### v9-17: v8 Regression

Re-run unit tests and deterministic/mocked v8 behavior. Confirm action normalization, trace, suspicion, causal repair, finish, and budget behavior have not regressed.

### v9-18: OSWorld v9 Experiment

Run the three frozen cases first. Expand to 10-20 unrelated clean tasks only after the three-case acceptance gate passes, then run fault benchmarks.

## Commit Policy

Each numbered implementation phase receives a focused commit after its tests pass. Never combine schema, runtime mutation, replanning, accessibility, and metric redesign into one commit.

## Immediate Acceptance Tests

The first implementation slice is complete when:

1. Existing 178 tests pass.
2. Synthetic visual/structured/persistence contracts validate correctly.
3. An unsupported structured contract is rejected without keyword logic.
4. Executor observability cannot override environment capability resolution.
5. Three different actions with the same contract and no information gain produce debt 3.
6. New relevant accessibility/structured evidence records progress.
7. A valid local patch preserves protected VERIFIED state and reconnects downstream nodes.
8. Invalid cyclic/unsupported patches are rejected without mutating live state.
