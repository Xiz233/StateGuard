from experiments.poc.metrics import preservation_metrics


def test_strict_progress_preservation_requires_untouched_verified_state():
    metrics = preservation_metrics({"S1", "S2"}, {"S2", "S3"}, set(), set(), {"S1"})
    assert metrics["actually_preserved_nodes"] == ["S1"]
    assert metrics["strict_progress_preservation_rate"] == 1.0
