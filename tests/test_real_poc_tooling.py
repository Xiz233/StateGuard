import pytest

from experiments.poc.manifest_validation import validate_distribution, validate_fault
from scripts.aggregate_poc import decision
from stateguard.core.dependency_graph import DependencyGraph


def graph():
    return DependencyGraph({"S1": [], "S2": ["S1"], "S3": ["S2"], "S4": ["S3"]})


def fault(fault_type="earlier_state_corruption"):
    return {
        "fault_id": f"task--{fault_type}",
        "type": fault_type,
        "root_node": "S2",
        "inject": {"trigger": {"subgoal_id": "S2", "action_type": "type",
                                "occurrence": 1},
                   "mutation": {"replace_text": "bad"}},
        "exposure": {"mode": "delayed", "trigger": {"subgoal_id": "S4"}},
        "expected_affected": ["S2", "S3", "S4"],
        "expected_preserved": ["S1"],
        "manual_review": {"approved": True, "approved_by": "reviewer",
                          "approved_at": "2026-08-14T00:00:00Z"},
    }


def test_earlier_fault_requires_real_downstream_exposure():
    validate_fault(fault(), graph())
    invalid = fault()
    invalid["exposure"]["trigger"]["subgoal_id"] = "S1"
    with pytest.raises(ValueError, match="downstream exposure"):
        validate_fault(invalid, graph())


def test_fault_distribution_is_exact_and_balanced():
    types = ("wrong_target", "wrong_value", "no_effect", "earlier_state_corruption")
    rows = []
    for task_index in range(12):
        for offset in range(2):
            rows.append({"task_id": f"task-{task_index}",
                         "spec": {"type": types[(task_index * 2 + offset) % 4]}})
    validate_distribution(rows)
    rows.pop()
    with pytest.raises(ValueError, match="24 faults"):
        validate_distribution(rows)


def test_go_decision_applies_all_gates():
    summaries = {
        "executor_only": {},
        "latest_retry": {"recovery_success_rate": 0.4},
        "stateguard": {"recovery_success_rate": 0.5, "first_root_accuracy": 0.7,
                       "strict_progress_preservation_rate": 0.8,
                       "false_intervention_rate": 0.15,
                       "fault_injection_validity_rate": 1.0},
    }
    assert decision(summaries)[0] == "GO"
    summaries["stateguard"]["fault_injection_validity_rate"] = 0.99
    assert decision(summaries)[0] == "NO-GO"
