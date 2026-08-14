# Metrics

Root predictions are typed `{step, fault_root}` events. The primary localization metric
is `first_root_accuracy`, comparing the first non-null diagnosis to ground truth;
`eventual_root_accuracy` uses the last diagnosis only as a diagnostic. Timing records
injection, exposure, first Guard detection, injection-to-detection delay, and whether
detection preceded exposure.

Every environment action is labeled `normal`, `verification`, or `repair`.
`repair_action_count` counts actual repair-phase environment actions, while
`repair_cycle_count` counts numbered RepairRequests. They are intentionally distinct.

At injection, verified nodes outside the ground-truth affected set form
`preservable_nodes`. `state_preservation_rate` checks final verification.
`strict_progress_preservation_rate` additionally requires that a node was never
invalidated and never re-targeted by a repair action; this stricter value is primary.

`InterventionEvent` covers repair requests, verification requests, and finish
rejections. False Intervention Rate uses only `certified_clean=true` episodes. On other
clean-looking live rollouts, interventions are counted but are not labeled false
positives because the Executor may have made a natural error. Fake results validate
plumbing only and are not scientific evidence.
