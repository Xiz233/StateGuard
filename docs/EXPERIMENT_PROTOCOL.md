# Experiment protocol

Each selected task has one clean episode and its declared fault episodes. Run the same
manifest in `executor_only`, `latest_retry`, and `stateguard` modes. The latest-retry
control receives only the fixed most-recent-operation message. Ground truth never
enters Executor or Guard inputs.

Formal runs require a clean Git tree unless `--allow-dirty` is explicitly supplied.
Use `--task ID` for debugging, `--tasks all` for batches, `--resume` to retain completed
episodes, and `--rerun-failed` to retry failed results. A dry run validates configuration,
providers, approved graphs, task/fault manifests, and logging paths without model/GUI calls.
