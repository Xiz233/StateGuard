# Controlled faults

`FaultInjectionEvent` records the action mutation and its step. A separate
`FailureExposureEvent` records when the harness exposes an external failure signal.
Fault specs select `exposure.mode`:

- `immediate`: exposure occurs on the injection transition;
- `delayed`: the corrupted state is observable normally, but the external signal waits
  for a configured later subgoal or step;
- `latent`: the backend changes internal state while the configured observation channel
  lacks that evidence, then reveals it at the exposure trigger.

`EarlierStateCorruptionInjector` independently mutates its root node and schedules
exposure; it is not a `WrongTargetInjector` subclass. Downstream actions may continue.
If StateGuard detects visible inconsistency before exposure, that is retained as a
legitimate early detection. Ground-truth spec/root/exposure data stays in
`fault_spec.json` and never enters Executor or Guard messages.
