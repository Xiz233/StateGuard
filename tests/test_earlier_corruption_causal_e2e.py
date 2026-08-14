import json

from tests.validity_helpers import run_earlier


def test_delayed_latent_corruption_localizes_earliest_root_and_preserves_s1(tmp_path):
    result, episode = run_earlier(tmp_path)
    rows = [json.loads(line) for line in (episode / "trajectory.jsonl").read_text().splitlines()]
    diagnosis = next(row for row in rows if row["guard_result"] and
                     row["guard_result"]["fault_root"] == "S2")
    assert result["fault_injected_step"] == 2
    assert result["failure_exposed_step"] == 4
    assert result["guard_first_detection_step"] == 4
    assert result["first_root_accuracy"] == 1
    assert result["eventual_root_accuracy"] == 1
    assert result["actually_preserved_nodes"] == ["S1"]
    assert result["strict_progress_preservation_rate"] == 1.0
    assert {"op": "fail", "node_id": "S2"} in diagnosis["state_updates"]
    stale = next(update["node_ids"] for update in diagnosis["state_updates"]
                 if update["op"] == "stale")
    assert set(stale) == {"S3", "S4"}
    repair_targets = [row["executor_proposal"]["subgoal_id"] for row in rows
                      if row["execution_phase"] == "repair"]
    assert repair_targets == ["S2", "S3", "S4"]
    assert result["task_state"]["nodes"]["S1"]["status"] == "verified"


def test_runtime_model_logs_do_not_receive_fault_or_exposure_ground_truth(tmp_path):
    _, episode = run_earlier(tmp_path)
    for name in ("executor_events.jsonl", "guard_events.jsonl"):
        text = (episode / name).read_text()
        assert all(key not in text for key in
                   ("root_node", "expected_affected", "expected_preserved", "exposure"))
