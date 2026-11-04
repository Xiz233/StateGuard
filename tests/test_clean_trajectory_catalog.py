import json

from scripts.build_clean_trajectory_catalog import build_catalog
from experiments.poc.runner import _archive_episode_attempt


def test_catalog_audits_semantic_trigger_occurrence(tmp_path):
    trajectory = tmp_path / "task-1--stateguard--clean" / "trajectory.jsonl"
    trajectory.parent.mkdir()
    rows = [
        {"step": 1, "executor_proposal": {"subgoal_id": "S1", "action": {
            "type": "click"}, "intent": "first"},
         "executed_action": {"type": "click", "x": 1, "y": 2}},
        {"step": 2, "executor_proposal": {"subgoal_id": "S1", "action": {
            "type": "click"}, "intent": "second"},
         "executed_action": {"type": "click", "x": 3, "y": 4}},
    ]
    trajectory.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = {"tasks": [{"task_id": "task-1", "faults": [{
        "fault_id": "f1", "type": "wrong_target",
        "inject": {"trigger": {"subgoal_id": "S1", "action_type": "click",
                                "occurrence": 2}},
    }]}]}
    catalog = build_catalog([str(trajectory)], manifest)
    audit = catalog["fault_trigger_audit"][0]
    assert audit["valid"] is True
    assert audit["selected_action"]["step"] == 2
    assert catalog["trigger_validity_rate"] == 1.0


def test_catalog_prefers_trigger_coverage_over_longer_trajectory(tmp_path):
    paths = []
    for attempt, actions in (("a", [("S1", "click")]),
                             ("b", [("S2", "type"), ("S2", "type")])):
        trajectory = tmp_path / attempt / "task-1--stateguard--clean" / "trajectory.jsonl"
        trajectory.parent.mkdir(parents=True)
        rows = [{"step": i, "executor_proposal": {"subgoal_id": node,
                 "action": {"type": action_type}},
                 "executed_action": {"type": action_type}}
                for i, (node, action_type) in enumerate(actions, 1)]
        trajectory.write_text("".join(json.dumps(row) + "\n" for row in rows))
        paths.append(str(trajectory))
    manifest = {"tasks": [{"task_id": "task-1", "faults": [{
        "fault_id": "f", "type": "wrong_value",
        "inject": {"trigger": {"subgoal_id": "S1", "action_type": "click"}},
    }]}]}
    catalog = build_catalog(paths, manifest)
    assert "/a/" in catalog["tasks"]["task-1"]["trajectory"]


def test_retry_archives_partial_episode(tmp_path):
    episode = tmp_path / "episodes" / "task--stateguard--clean"
    episode.mkdir(parents=True)
    (episode / "trajectory.jsonl").write_text("partial\n")
    destination = _archive_episode_attempt(episode, tmp_path)
    assert not episode.exists()
    assert (destination / "trajectory.jsonl").read_text() == "partial\n"
