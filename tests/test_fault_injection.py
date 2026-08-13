"""Milestone 6: synthetic fault injection (指引.txt §25/26) — every fault
type is injectable, ground truth matches the graph, and the full
execute -> localize -> invalidate -> repair -> reverify loop recovers."""

import pytest

from examples.synthetic_tasks.tasks import TASKS
from fault_injection.injector import inject, make_cases
from fault_injection.harness import run_episode
from fault_injection.fault_types import INJECTABLE
from stateguard.core.schema import FaultType


def test_all_fault_types_injectable():
    assert {c.ground_truth["fault_type"] for c in make_cases(TASKS)} == \
        set(ft.value for ft in INJECTABLE)


def test_ground_truth_format():
    spec = next(t for t in TASKS if t["name"] == "spreadsheet")
    case = inject(spec, FaultType.WRONG_TARGET)
    gt = case.ground_truth
    assert gt["fault_type"] == "wrong_target"
    assert gt["fault_root"] == "S3"
    assert gt["affected_nodes"] == ["S3", "S4", "S5"]  # §26 example
    assert gt["preservable_nodes"] == ["S1", "S2"]


def test_wrong_target_detected_and_recovered():
    spec = next(t for t in TASKS if t["name"] == "spreadsheet")
    case = inject(spec, FaultType.WRONG_TARGET)
    m = run_episode(case.task_spec, "wt", hints=case.hints, fixes=case.fixes,
                    gt=case.ground_truth)
    assert m["predicted_root"] == "S3"
    assert m["predicted_fault_type"] == "wrong_target"
    assert m["root_correct"] is True
    assert m["recovered"] is True
    assert m["preserved_nodes"] == 2  # S1, S2


@pytest.mark.parametrize("ftype", list(INJECTABLE))
def test_every_fault_type_recovers(ftype):
    """One representative episode per fault type must localize + recover."""
    for spec in TASKS:
        try:
            case = inject(spec, ftype)
        except ValueError:
            continue
        m = run_episode(case.task_spec, case.name, hints=case.hints,
                        fixes=case.fixes, gt=case.ground_truth)
        assert m["root_correct"] is True, f"{case.name}: {m['predicted_root']}"
        assert m["recovered"], f"{case.name} did not recover"
        break
    else:
        raise AssertionError(f"no injectable task for {ftype}")


def test_clean_episode_has_no_false_intervention():
    for spec in TASKS:
        m = run_episode(spec, spec["name"])
        assert m["contradictions"] == 0, spec["name"]
        assert m["recovered"], spec["name"]


def test_missing_subgoal_skips_necessary_step():
    spec = next(t for t in TASKS if t["name"] == "config_persist")
    case = inject(spec, FaultType.MISSING_SUBGOAL)
    m = run_episode(case.task_spec, "ms", hints=case.hints, fixes=case.fixes,
                    gt=case.ground_truth)
    assert m["predicted_root"] == "S2"
    assert m["predicted_fault_type"] == "missing_subgoal"
    assert m["recovered"]


def test_not_persisted_requires_reopen_evidence():
    spec = next(t for t in TASKS if t["name"] == "config_persist")
    case = inject(spec, FaultType.NOT_PERSISTED)
    m = run_episode(case.task_spec, "np", hints=case.hints, fixes=case.fixes,
                    gt=case.ground_truth)
    assert m["predicted_root"] == "S2"
    assert m["predicted_fault_type"] == "not_persisted"
    assert m["recovered"]


def test_dependency_violation_uses_unverified_parent():
    spec = next(t for t in TASKS if t["name"] == "config_persist")
    case = inject(spec, FaultType.DEPENDENCY_VIOLATION)
    m = run_episode(case.task_spec, "dv", hints=case.hints, fixes=case.fixes,
                    gt=case.ground_truth)
    assert m["predicted_root"] == "S2"
    assert m["predicted_fault_type"] == "dependency_violation"
    assert m["recovered"]


def test_unsupported_fault_target_raises():
    spec = {"name": "x", "nodes": [], "fault_targets": {}}
    with pytest.raises(ValueError):
        inject(spec, FaultType.WRONG_TARGET)
