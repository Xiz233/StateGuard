from experiments.poc.metrics import false_intervention_metrics


def test_natural_error_on_noncertified_rollout_is_not_false_positive():
    metrics = false_intervention_metrics([{"intervention_type": "repair_request"}], False)
    assert metrics["guard_intervention_count"] == 1
    assert not metrics["false_intervention_episode"]
    assert metrics["false_intervention_event_count"] == 0
