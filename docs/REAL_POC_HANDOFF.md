# Real PoC Handoff

Status: code and standalone infrastructure are ready; experiment is stopped at the
required strong multimodal Guard API gate.

## Server

- Hardware: 8 x NVIDIA A40 48 GB; all GPUs currently allocated to existing endpoints
- Audit path: `/data/research/stateguard_runs/server2_audit`
- KVM/Docker: Docker hello-world PASS; `/dev/kvm` maps successfully through Docker

## OSWorld

- Target path: `/data/research/projects/OSWorld-StateGuard`
- Required version: OSWorld-Verified from official `xlang-ai/OSWorld`
- Commit: `091f5ef1d5544bc74953c77875d5feb5bed30108`
- Provider: Docker, reusing the existing `Ubuntu.qcow2` read-only
- Audit decision: REUSE
- Standalone smoke: PASS for reset, screenshot, click, type, hotkey, scroll, drag,
  wait, evaluator, and same-task reset
- Smoke artifacts: `/data/research/stateguard_runs/osworld_smoke`

## Executor

- Model: `Qwen3-VL-32B-Instruct`
- Checkpoint: `/data/research/models/Qwen3-VL-32B-Instruct`
- Endpoint: `http://127.0.0.1:8032/v1`
- Deployment: existing vLLM, tensor parallel 4
- Multimodal smoke: PASS; reported model ID `Qwen3-VL-32B-Instruct`, about 5 seconds
- Smoke report: `/data/research/stateguard_runs/model_smoke/executor.md`

## StateGuard

- Provider: OpenCode Go, Anthropic-compatible `/messages`
- Model: `qwen3.7-plus`
- Base URL: `https://opencode.ai/zen/go/v1`
- Semantic smoke: required before any experiment
- Code path: `/data/research/projects/StateGuard`
- Tests: 98 passed locally; server verification pending final sync

## Tasks and faults

- Tasks: 12 deterministic candidates discovered (4 Calc, 3 Writer, 3 Chrome, 2 OS)
- Discovery artifacts: `/data/research/stateguard_runs/task_discovery`
- DAGs: pending named manual approval
- Faults: pending 24 named manual approvals; six each of wrong target, wrong value,
  no effect, and earlier-state corruption

## Experiments

- OSWorld standalone smoke: PASS
- Three-task clean smoke: pending
- Three-task recovery smoke: pending
- Earlier-causal case: pending
- 108-episode PoC: pending
- GO / NO-GO: pending

## Current blocker

The OpenCode Guard configuration is installed, but `OPENCODE_GO_API_KEY` must be
set on the server. Qwen3.7 Plus must then pass the six-case image semantic smoke;
endpoint availability alone does not prove it is suitable as a multimodal Guard.
Do not replace it with the local Qwen Executor merely to continue.

## Next action

Deploy this repository without overwriting existing assets, run the audits in
`docs/REAL_POC_RUNBOOK.md`, configure the Guard API, and complete manual task/DAG/
fault approval before launching real episodes.
