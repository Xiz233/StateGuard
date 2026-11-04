# v10 Audit: Artificial Fault Dependencies

## Decision

Artificial fault injection is no longer part of the primary experiment. It is
retained as an optional `controlled_fault_diagnostic` capability for mechanism
tests, especially delayed earlier-state-corruption localization.

In `experiment.design: natural_failure`:

- one episode is generated per task/run seed/system mode;
- no `FaultInjector` is constructed;
- `executed_action` is the Executor proposal;
- no injection/exposure hook runs;
- no `fault_spec.json` is written;
- no injected-ground-truth metric is used by the primary report.

## Previous dependency graph

```text
fault-matrix config
  -> task manifest embeds task.faults
  -> runner expands clean + every fault
  -> experiments.poc.faults.make_injector()
  -> EpisodeRunner.run(..., injector)
  -> inject() between Executor proposal and env.step()
  -> poll_exposure()
  -> trajectory injection/exposure records
  -> injected-step/root/preservation metrics
  -> fault-oriented summary and report_v9_matrix.py
```

## Main-path removals

| Component | Previous behavior | Natural v10 behavior |
|---|---|---|
| `task.faults` | Expanded fault scenarios | Stripped while loading the natural manifest |
| `faults.enabled` | Required by every config | Not required |
| `make_injector()` | Part of every episode path | Called only when an explicit diagnostic spec exists |
| `inject()/poll_exposure()` | Wrapped environment actions | Never invoked |
| `fault_spec.json` | Written even for clean | Not created |
| Fault metadata hash | Written for every run | Omitted |
| Fault recovery/root accuracy | Headline metrics | Excluded from natural summary/report |
| Episode identity | `task--mode--fault-id` | `task--mode--seed-N` |

## Retained optional diagnostics

These remain for reproducibility and explicit mechanism studies:

```text
experiments/poc/faults/
configs/faults/osworld/
configs/poc/fault_manifest.yaml
fault_injection/
scripts/report_v9_matrix.py
historical v1-v9 configs and docs
```

They should use an explicitly named design:

```yaml
experiment:
  design: controlled_fault_diagnostic
faults:
  enabled: true
```

Historical configs without `experiment.design` default to controlled diagnostic
for backward compatibility.

## Compatibility fields

`EpisodeResult` still contains legacy injection/root fields so old results and
tests remain readable. Natural results leave them empty/default, and
`RunLogger._summarize_natural()` does not publish them as research outcomes.

## New primary path

```text
natural task manifest
  -> task/run-seed identity per mode
  -> Executor proposal
  -> executed_action = proposal.action
  -> real OSWorld observation/evaluator
  -> natural-failure taxonomy
  -> paired rescue report
```

Reports are intentionally separate:

- Controlled legacy: `scripts/report_v9_matrix.py`
- Natural primary: `scripts/report_natural_failure.py`
- Completeness gate: `scripts/check_natural_completeness.py`
