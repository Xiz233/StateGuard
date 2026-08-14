# Architecture

StateGuard keeps one correction module and one explicit task DAG. The runtime flow is:

`Observation -> Executor -> validated GUI action -> Environment -> Guard -> fault_root
-> deterministic descendants -> RepairRequest -> Executor -> re-verification`.

Structured predicates use the rule backend when decisive. Visual transitions use one
MLLM request containing the current before/after screenshots and at most ten textual
history records. Only the predicted root is semantic; affected nodes always come from
`DependencyGraph`. `experiments/` owns fault labels and logging, while all OSWorld API
variation stays under `integrations/osworld/`.
