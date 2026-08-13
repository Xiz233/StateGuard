#!/usr/bin/env python3
"""Phase I key demo (指引.txt §31):

    python scripts/run_mock_demo.py

Shows: task init -> S1/S2 verified -> injected S3 WRONG_TARGET (Sheet2 ->
Sheet1) -> StateGuard localizes fault_root = S3 (the earliest violated
dependency, not the latest action) -> S3 FAILED, affected descendants
STALE, S1/S2 preserved -> minimal repair -> re-execution -> task complete.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.guard.state_guard import StateGuard
from replay.mock_environment import MockEnvironment
from examples.synthetic_tasks.tasks import TASKS
from examples.synthetic_tasks.spec_executor import SpecExecutor
from fault_injection.injector import inject
from stateguard.core.schema import FaultType


def statuses(state):
    return ", ".join(f"{nid} {state.get(nid).status.value.upper()}"
                     for nid in sorted(state.nodes))


def main() -> None:
    spec = next(t for t in TASKS if t["name"] == "spreadsheet")
    case = inject(spec, FaultType.WRONG_TARGET)  # S3 selects Sheet1 instead of Sheet2

    env = MockEnvironment(case.task_spec)
    state = compile_from_spec(case.task_spec)
    executor = SpecExecutor(case.task_spec)
    guard = StateGuard()
    obs = env.reset()

    print("Task initialized")
    print(statuses(state))
    print()

    repair_context = None
    fault_shown = False
    fixes_applied = False
    step = 0
    while True:
        step += 1
        proposal = executor.act(obs, state, repair_context)
        if proposal is None:
            print("EXECUTOR STUCK")
            break
        if proposal.is_finish:
            result = guard.verify_finish(state, obs)
            if result.approved:
                break
            repair_context = result.repair
            continue
        before = obs
        after = env.step(proposal.action)
        result = guard.verify_transition(state, before, proposal, after)
        obs = after

        if result.judgement == "contradicted":
            if not fixes_applied:
                for action_name, effect in case.fixes["effects"].items():
                    env.fix_action(action_name, effect)
                executor.fix(case.fixes)
                fixes_applied = True
            repair_context = result.repair
            if not fault_shown:
                fault_shown = True
                print("Injected fault:")
                print(f"S3 {result.fault_type.upper()}")
                print()
                print("StateGuard:")
                print(f"fault_root = {result.fault_root}")
                print()
                print("State update:")
                print(f"{result.repair.fault_root} FAILED")
                stale = result.repair.stale_nodes
                print(", ".join(stale) + " STALE" if stale else "(no stale nodes)")
                print()
                print("Preserved:")
                print(", ".join(result.repair.preserve_nodes))
                print()
                print("Repair target:")
                print(f"Restore {state.get(result.fault_root).description} "
                      f"without repeating {', '.join(result.repair.preserve_nodes)}")
                print()
                print("Repair executed")
                print()
        elif result.judgement == "verified":
            print(f"{proposal.subgoal_id} VERIFIED")
        elif result.judgement == "unknown":
            print(f"{proposal.subgoal_id} EXECUTED (verification target: "
                  f"{result.verification_target})")

        state.apply(result.state_updates)

    print()
    print("Task complete")


if __name__ == "__main__":
    main()
