from experiments.poc.metrics import root_prediction_metrics


def test_eventual_root_is_retained_as_diagnostic():
    metrics = root_prediction_metrics([{"step": 4, "fault_root": "S3"},
                                       {"step": 6, "fault_root": "S2"}], "S2")
    assert metrics["eventual_root_prediction"] == "S2"
    assert metrics["eventual_root_accuracy"] == 1
