# Publication security review

Date: 2026-11-04

## Scope

This release publishes the current StateGuard source snapshot and a pinned
StructAgent fusion overlay. It does not merge private server Git history or
upload raw experiment directories. The previously published repository history
is retained; this review is not a forensic audit of every historical commit.

The publication copy was prepared separately from the working experiment
repositories. No server model service, VM or evaluation was started or changed.
Algorithmic behavior and the known verification-budget limitations are
preserved. Changes made for publication are path portability, documentation,
ignore rules, source assembly, and Python 3.12 test-mocking compatibility.

## Sensitive data checks

- Exported only Git-tracked and non-ignored source files from StateGuard, plus
  an explicit allowlist of fusion implementation files and tests.
- Excluded local model-provider configuration, secret files, virtual
  environments, VM images, model weights, recordings and raw rollout logs.
- Replaced private server and workstation paths with illustrative paths.
  Historical runbooks using `/data/research` are examples, not a deployment
  requirement.
- Checked email addresses. The six source occurrences use the reserved
  `example.com` domain in synthetic tasks; no personal email was found.
- Checked API-key patterns, private-key markers, literal credentials, private
  machine identifiers, addresses and file names.
- Ran `detect-secrets 1.5.0` against publication files with all default detectors
  and network verification disabled. This avoids sending candidate values to
  providers. Its initial 49 findings were reviewed as public OSWorld VM defaults
  (40), environment-variable names (2), synthetic test credentials (4), an
  upstream commit SHA (1), embedded fake-backend PNG bytes (1), and the local
  vLLM `EMPTY` placeholder (1). No actual provider secret was identified.
- `.gitignore` now covers `.env` variants, private-key files, local model
  settings, logs, run/results directories, recordings and VM images. Ignore
  rules do not protect files already tracked, so the content scan remains
  necessary.

The OSWorld VM's public default password is retained for benchmark
compatibility. It is not a production server password. Real deployment
credentials must stay outside Git and must not be reused from benchmark VMs.

## Validation

- StateGuard test suite: 261 passed on Python 3.12.
- Fusion regression suite: 57 passed on Python 3.12.
- Source assembly was tested by cloning the fixed upstream commit and applying
  the published overlay plus this checkout's StateGuard package.
- The local launcher exposes baseline, VM and cache paths through environment
  configuration; the remote launcher accepts an explicit secret-file path.
- No real-model inference or OSWorld rollout was run as part of publication.

These checks reduce accidental disclosure risk; no pattern-based scanner can
prove that arbitrary content is free of all possible sensitive information.
Do not publish future rollout archives without a separate content review.

## Entry points

- Main runtime and experiments: repository README.
- Fusion preparation: `scripts/setup_structagent_fusion.py`.
- Fusion deployment and settings: `integrations/structagent/README.md`.
- Actual 60-task results and unresolved problems:
  `docs/LOCAL60_VERIFICATION_BUDGET_ANALYSIS_20261104.md`.
