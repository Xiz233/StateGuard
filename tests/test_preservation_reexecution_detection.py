from experiments.poc.metrics import preservation_metrics


def test_reexecution_disqualifies_strict_preservation():
    metrics = preservation_metrics({"S1"}, {"S2"}, set(), {"S1"}, {"S1"})
    assert metrics["state_preservation_rate"] == 1.0
    assert metrics["reexecuted_preserved_nodes"] == ["S1"]
    assert metrics["strict_progress_preservation_rate"] == 0.0
