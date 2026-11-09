# StructAgent fusion integration

This directory distributes the StateGuard fusion modifications as an overlay,
not a second copy of the benchmark and not a replacement for the StateGuard
runtime. Upstream is StructAgent commit
`bd9452afab6c9c472af8d9a1fff2d7f4c33d499e` from
<https://github.com/WenyiWU0111/StructAgent>.

The overlay preserves the upstream Apache-2.0 LICENSE and NOTICE. Modified
upstream files add endpoint routing, bounded episode recovery, progressive
verification hooks, and browser DOM timeout handling. Added files provide the
OpenCode client, verification implementation, launchers, task-ID manifests and
regression tests. Benchmark task definitions, VM images, model weights, raw
trajectories and private configuration are intentionally not redistributed here.

## Prepare the source

From the StateGuard checkout, with Python 3.10 or newer:

```bash
python scripts/setup_structagent_fusion.py --destination ../StructAgent-fusion
```

This clones the pinned upstream, copies the overlay and this checkout's
`stateguard` package into `vendor/stateguard`, and records source hashes in
`FUSION_SOURCE.json`. It refuses an existing destination. It does not install
dependencies, download models, start a VM, or spend API credits.

Install the upstream runtime dependencies in a separate environment following
the upstream documentation. The lightweight fusion tests can run without a VM:

```bash
cd ../StructAgent-fusion
python -m pip install pytest PyYAML requests Pillow beautifulsoup4
PYTHONPATH="$PWD/vendor:$PWD" python -m pytest -q tests
```

## Local inference reproduction

Serve `Qwen/Qwen3.5-9B` at `127.0.0.1:8110` and `Qwen/Qwen3.5-27B` at
`127.0.0.1:8112`, using vLLM's OpenAI-compatible `/v1` endpoints with vision
support. This integration does not start or reconfigure model services.

Set the paths for your own machine, not those from historical runbooks:

```bash
export OSWORLD_VM_PATH=/path/to/Ubuntu.qcow2
export FUSION_BASELINE_RUN=/path/to/historical/main60_run
export FUSION_BASELINE_REPO=/path/to/historical/StructAgent
export HF_HOME=/path/to/huggingface-cache
export TMPDIR=/tmp
PYTHONPATH="$PWD/vendor:$PWD" python scripts/run_fusion_local60.py \
  --run-dir /path/to/new-run --preflight-only
```

The baseline run must contain `main60.json`; its exact task selection and the
baseline repository's task definitions are checked before execution. Keep your
historical baseline directory immutable. Remove `--preflight-only` only when
you intend to run the 60 tasks. Run directories must be new.

Local inference explicitly drops API credentials and rejects non-loopback
model endpoints. Its present settings remain 100 main-loop steps, three
verification rounds per target set, and twelve progressive-verifier calls per
task. **Task wall-time and aggregate model-call budgets are not enabled in this
historical local configuration.** No budget policy fix is claimed by this release.

## Optional stagnation shadow run

The local runner can score unresolved milestones at actor-burst exit before
progressive verification. Scores are recorded in each task's
`stagnation_shadow.jsonl`. This mode only observes. The verifier still runs
with its original budgets and the final DONE gate follows its usual path.

Install `numpy`, CPU PyTorch and `transformers>=4.57,<5` in the fusion runtime.
Set these variables before invoking the local runner above:

```sh
export FUSION_STAGNATION_SHADOW=1
export FUSION_STAGNATION_MODEL_DIR=/absolute/path/to/modernbert_large
export FUSION_STAGNATION_HEAD=/absolute/path/to/modernbert_large__causal_actions_and_observed_controls__embedding.npz
```

Use the matching frozen ModernBERT-large weights and embedding-only PCA/logistic
head. The files are supplied locally. The scorer does no network fetches or GUI
probes. Each record contains status, step, target IDs and elapsed time. Scored
records include `p_stagnant` and the observation step IDs. Missing history or
failed scoring is logged and verification continues. Live inputs use recorded
actions and existing accessibility observations, with no proposed action at the
boundary. Treat scores as experimental until calibrated on fusion trajectories.

## Optional OpenCode canary

The remote launcher reads a local, untracked secret file. It must contain your
own `OPENCODE_GO_API_KEY`, never a key committed to Git. Pass its path explicitly
with `--secrets` or set `STATEGUARD_SECRETS_FILE`; use restrictive file permissions.
Keep `OSWORLD_VM_PATH` set. The default selection has three tasks:

```bash
PYTHONPATH="$PWD/vendor:$PWD" python scripts/run_fusion_canary.py \
  --run-dir /path/to/new-canary --secrets /path/to/private/.env.secrets
```

This command uses a paid external service. Inspect the launcher budgets and
your provider account before running it. Allowance estimates are not an
authoritative account-balance measurement. Do not use `--full60` without
explicitly choosing to expand the experiment.

## Current limitations

The three-stage verifier implements current evidence, selected history and
restricted read-only probes. It is inspired by progressive verification; it is
not a reproduction of VAGEN training. StateGuard evidence contracts and debt
tracking are integrated, but the hard per-scope attempt counter can interrupt
multi-step repairs. Structured CLI output is not yet fully connected to the
progressive verifier, and document probes can omit relevant content. See
`../../docs/LOCAL60_VERIFICATION_BUDGET_ANALYSIS_20261104.md` for the audited
results, limitations and proposed fixes.
