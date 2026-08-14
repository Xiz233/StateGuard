from experiments.poc.metrics import root_prediction_metrics


def test_first_root_is_primary_accuracy():
    metrics = root_prediction_metrics([{"step": 4, "fault_root": "S3"},
                                       {"step": 6, "fault_root": "S2"}], "S2")
    assert metrics["first_root_prediction"] == "S3"
    assert metrics["first_root_accuracy"] == 0
