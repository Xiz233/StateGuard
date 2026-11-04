# Real OSWorld-Verified PoC Runbook

This runbook implements the first StateGuard PoC without replacing existing
server assets. Run commands from `/data/research/projects/StateGuard` unless noted.

## Fixed layout

```text
/data/research/projects/StateGuard
/data/research/projects/OSWorld-StateGuard
/data/research/models/Qwen3-VL-32B-Instruct
/data/research/stateguard_runs/server2_audit
/data/research/stateguard_runs/osworld_smoke
/data/research/stateguard_runs/model_smoke
/data/research/stateguard_runs/task_discovery
/data/research/stateguard_runs/poc_smoke_3tasks
/data/research/stateguard_runs/poc_v1_108
```

Never overwrite an existing directory. Audit first, then reuse an exact match or
deploy a separate copy.

## 1. Audit and standalone gates

```bash
python scripts/audit_server.py --output /data/research/stateguard_runs/server2_audit
python scripts/audit_osworld.py \
  --root /data/research/projects/OSWorld-StateGuard \
  --output /data/research/stateguard_runs/server2_audit/osworld.md
docker run --rm hello-world
```

Run `scripts/smoke_osworld.py` with an approved harmless task and a reviewed JSON
action sequence. Use `--require-full-action-set` for the adapter acceptance gate.
The sequence must exercise click, type, hotkey, scroll, drag, and wait, save each
screenshot, call the evaluator, and reset the same task.

Pass `--osworld-root /data/research/projects/OSWorld-StateGuard`,
`--vm-path /data/research/ui-mopd-repro/repos/OSWorld/docker_vm_data/Ubuntu.qcow2`, and
`--cache-dir /data/research/stateguard_runs/cache` to reuse the existing VM image
read-only without downloading or copying it.

## 2. Model gates

Executor variables must resolve to the already deployed exact checkpoint:

```bash
export EXECUTOR_BASE_URL=http://127.0.0.1:8032/v1
export EXECUTOR_API_KEY=EMPTY
export EXECUTOR_MODEL=/data/research/models/Qwen3-VL-32B-Instruct
python scripts/test_model_api.py --provider executor_qwen \
  --image /data/research/stateguard_runs/osworld_smoke/before.png \
  --report /data/research/stateguard_runs/model_smoke/executor.json
```

The Guard is configured for OpenCode Go Qwen3.7 Plus through the Anthropic-compatible
`/messages` endpoint. Set only `OPENCODE_GO_API_KEY`, then fill the six screenshot paths in
`configs/model_smoke/guard_cases.example.json`, then run:

```bash
cp configs/models.example.yaml configs/models.yaml
export OPENCODE_GO_API_KEY=YOUR_KEY
python scripts/test_model_api.py --provider stateguard_api \
  --cases configs/model_smoke/guard_cases.json \
  --report /data/research/stateguard_runs/model_smoke/guard.json
python scripts/check_readiness.py --backend real \
  --osworld-root /data/research/projects/OSWorld-StateGuard
```

Stop if the Guard cannot consume images or distinguish verified, contradicted,
and unknown transitions. Do not silently substitute the Executor checkpoint.

## 3. Tasks, DAGs, and faults

```bash
python scripts/prepare_osworld_poc.py \
  --benchmark-root /data/research/projects/OSWorld-StateGuard \
  --output configs/tasks/osworld \
  --artifacts /data/research/stateguard_runs/task_discovery
python scripts/prepare_task_graphs.py --manifest configs/poc/selected_tasks.yaml
python scripts/review_task_graphs.py --manifest configs/poc/selected_tasks.yaml \
  --reviewer REVIEWER_NAME
python scripts/prepare_fault_manifest.py
python scripts/validate_fault_manifest.py --allow-unapproved
python scripts/review_faults.py --reviewer REVIEWER_NAME
python scripts/validate_fault_manifest.py
```

The selected set is exactly 12 tasks: 4 Calc, 3 Writer, 3 Chrome, and 2 file/OS.
All DAGs and all 24 faults require a named, timestamped manual approval. Faults
must be balanced at six per type and two per task. Runtime prompts must not expose
hidden evaluator state or controlled-fault ground truth.

## 4. Smoke and formal matrix

First run three clean episodes, then three StateGuard fault episodes, and inspect
their screenshots and trajectories manually. At least one must demonstrate a real
earlier-state corruption detected downstream and repaired from the causal root.

```bash
python scripts/run_poc_osworld.py --mode stateguard --task TASK_ID --allow-dirty
python scripts/run_poc_matrix.py --dry-run
python scripts/run_poc_matrix.py --resume
python scripts/aggregate_poc.py \
  --runs /data/research/stateguard_runs/poc_v1_108 \
  --output /data/research/stateguard_runs/poc_v1_108/report.md
```

Formal runs require a clean StateGuard worktree. The matrix is fixed at 36
conditions in each of `executor_only`, `latest_retry`, and `stateguard`, for 108
episodes total. All modes share task reset, fault mutation, Qwen model, decoding,
history window, and step limits. Temperature is zero in the provider config.

## Stop conditions

Stop and report evidence if OSWorld is not Verified, KVM is unavailable, the exact
Qwen checkpoint cannot run, the Guard is not strongly multimodal, the action map
is unreliable, evaluator behavior differs from the target setting, or 24 credible
controlled faults cannot be constructed. Record the problem, evidence, attempted
fixes, alternatives, and recommendation in `docs/REAL_POC_HANDOFF.md`.
