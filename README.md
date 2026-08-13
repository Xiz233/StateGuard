# StateGuard

**Verified task state + causal fault localization + dependency-aware minimal repair.**

Phase I: core mechanism only — no GUI benchmarks, no baselines, no
training (指引.txt §0/37). The goal is one clean, testable, benchmark-independent
task-state repair mechanism:

> StateGuard maintains an explicit verified task state, identifies the earliest
> violated dependency when execution becomes inconsistent, invalidates only the
> downstream progress affected by that violation, and provides a minimal repair
> target while preserving independent verified progress.

## Quickstart

```bash
python scripts/run_mock_demo.py            # §31 key demo (fault -> localize -> repair)
python scripts/run_offline_eval.py         # §27 offline metrics over 12 synthetic tasks
pytest                                     # all unit tests
```

## Layout (指引.txt §6; `stateguard_project/` == this directory)

```
stateguard/            runtime core (never sees ground truth / benchmarks, §22/35)
  core/                NodeStatus, Evidence, TaskNode, VerifiedTaskState, DependencyGraph
  compiler/            compile_from_spec / compile_from_instruction (LLM stub)
  guard/               StateGuard: verify / localize / repair + prompts
  interfaces/          Observation, Action, EnvironmentAdapter
replay/                MockEnvironment (symbolic) + ReplayEnvironment (saved trajectories)
fault_injection/       offline labeling: fault injection + ground truth + episode harness
eval/                  localization / recovery / progress metrics + per-episode logging
examples/synthetic_tasks/  12 tasks (linear/branching/independent/multi-source/multi-output)
scripts/               run_mock_demo.py, run_offline_eval.py
tests/                 pytest suite
```

## Core ideas

- **EXECUTED != VERIFIED**: an action executed but unconfirmed stays EXECUTED
  (`UNKNOWN` judgement + verification target, §20). Persistence-style subgoals
  (save / commit) are only VERIFIED after a `verify_action` (e.g. reopen).
- **Only the fault root is a judgement**: downstream invalidation is
  deterministic graph code (`graph.descendants(root)`, §11). Independent
  VERIFIED nodes are never touched (§12/13).
- **Minimal repair**: a `RepairRequest` carries preserve / stale / reverify
  sets — never a regenerated plan (§15).
- **Consistency sweep**: every step, the guard re-checks VERIFIED nodes'
  `expected_result` against the observation, so wrong facts are caught at their
  true source (e.g. value written to Sheet1 is localized to S3 "select Sheet2",
  not to the save step, §5.2).
- **Offline separation** (§22): `stateguard/` never imports `fault_injection/`,
  `eval/`, or ground truth. Fault labels live in the offline side only.

## Runtime interface (指引.txt §18 — kept stable)

```python
task_state = compiler.compile(task)
obs = env.reset()
repair_context = None
while True:
    proposal = executor.act(observation=obs, task_state=task_state,
                            repair_context=repair_context)
    if proposal.is_finish:
        result = guard.verify_finish(task_state=task_state, observation=obs)
        if result.approved:
            break
        repair_context = result.repair
        continue
    before = obs
    after = env.step(proposal.action)
    result = guard.verify_transition(task_state=task_state, before=before,
                                     proposal=proposal, after=after)
    task_state.apply(result.state_updates)
    repair_context = result.repair if result.requires_repair else None
    obs = after
```

## Logging (指引.txt §28)

Every episode writes under `run/<episode>/`: `task.json`,
`task_state_initial.json`, `task_state_final.json`, `trajectory.jsonl`,
`guard_events.jsonl`, `repair_events.jsonl`, `metrics.json`.

## Intentional simplifications (ponytail mode)

- Rule-based verifier / localizer (learned versions plug in behind
  `prompts.py` schemas).
- No `executor` module in `stateguard/`: the spec-driven executor is an example
  component (`examples/synthetic_tasks/spec_executor.py`).
- Declarative action effects (`{var: literal|"@param"}`) instead of a world model.
- `graphlib.TopologicalSorter` from the stdlib for topological order/cycles.
