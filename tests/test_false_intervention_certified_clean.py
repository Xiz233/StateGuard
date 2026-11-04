from experiments.poc.metrics import false_intervention_metrics


def test_certified_clean_intervention_counts_as_false_positive():
    metrics = false_intervention_metrics([{"intervention_type": "repair_request"}], True)
    assert metrics["false_intervention_episode"]
    assert metrics["false_intervention_event_count"] == 1


def test_normal_verification_control_is_not_a_false_intervention():
    metrics = false_intervention_metrics([
        {"intervention_type": "finish_rejection"},
        {"intervention_type": "verification_request"},
    ], True)
    assert metrics["guard_intervention_count"] == 2
    assert not metrics["false_intervention_episode"]
    assert metrics["false_intervention_event_count"] == 0
