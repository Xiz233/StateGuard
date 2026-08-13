# PoC protocol

Primary results use fixed, human-reviewed task DAGs and one of `executor_only`,
`latest_retry`, or `stateguard`. Controlled fault ground truth stays in experiments.
Episodes record metadata, task, graph, trajectories, Guard/repair events, screenshots,
and result under `runs/<run_id>/<episode_id>/`.
