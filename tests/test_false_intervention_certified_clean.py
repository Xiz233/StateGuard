from experiments.poc.metrics import false_intervention_metrics


def test_certified_clean_intervention_counts_as_false_positive():
    metrics = false_intervention_metrics([{"intervention_type": "repair_request"}], True)
    assert metrics["false_intervention_episode"]
    assert metrics["false_intervention_event_count"] == 1
