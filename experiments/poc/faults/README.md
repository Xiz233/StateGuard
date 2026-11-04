# Controlled Fault Diagnostics (Legacy / Optional)

This package is not part of the Natural Failure Rescue main experiment.

It is retained only for explicit mechanism diagnostics such as delayed
earlier-state-corruption localization. Main v10 configs use
`experiment.design: natural_failure`; that path never constructs a
`FaultInjector`, never mutates an Executor action, and never writes a
`fault_spec.json` artifact.

Any future controlled run must use an explicitly named
`controlled_fault_diagnostic` config and report. Its recovery metrics must not
be merged into natural task success or Natural Failure Rescue Rate.
