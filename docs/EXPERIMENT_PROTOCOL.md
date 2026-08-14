# Experiment protocol

Each task has clean and declared-fault episodes in `executor_only`, `latest_retry`,
and `stateguard`. Four times are distinct: **injection time** mutates an executed
transition; **exposure time** emits an external failure signal; **detection time** is
the Guard's first non-null causal root; **repair time** contains environment actions
executed under a numbered `RepairRequest`. Detection may precede exposure and is then
recorded as `early_detection=true`.

`latest_retry` receives no signal at injection. Only a `FailureExposureEvent` enables
the generic current-state prompt on the following Executor call. The prompt contains
no fault type, root, timing, affected/preserved nodes, or dependency diagnosis.
StateGuard continues observing every transition normally; delayed exposure never
artificially suppresses an observation.

Formal runs require a clean Git tree unless `--allow-dirty` is supplied. Use `--task`
for debugging, `--tasks all` for batches, `--resume`/`--rerun-failed` for continuation,
and `--dry-run` for configuration validation. Only explicitly `certified_clean=true`
episodes enter the false-intervention denominator.
