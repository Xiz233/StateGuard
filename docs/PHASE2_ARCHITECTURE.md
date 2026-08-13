# Phase II-A architecture

`Observation` carries a screenshot path plus optional structured state. The Executor
proposes one GUI action through a provider-neutral `ModelClient`. `StateGuard` routes
decisive predicates to rules and visual ambiguity to one MLLM call. The model may
select only the causal root; `DependencyGraph` deterministically invalidates its
descendants and builds a minimal `RepairRequest`. `EpisodeRunner` feeds that request
back to the Executor and stops after the configured repair/step limits.

OSWorld and controlled faults remain outside `stateguard/`; neither benchmark labels
nor oracle repair can enter the runtime core.
