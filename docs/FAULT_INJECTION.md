# Controlled faults

Fault manifests define a trigger, root, explicit mutation, affected nodes, and preserved
nodes. `wrong_target` uses reviewer-provided coordinates, `wrong_value` replaces text,
`no_effect` executes wait instead of the proposal, and `earlier_state_corruption` mutates
an early dependency without disclosing its root. Every trajectory records original and
executed actions. Ground truth is stored in `fault_spec.json`, never in runtime prompts.
