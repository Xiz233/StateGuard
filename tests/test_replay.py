"""Replay environment (指引.txt §23) + mock environment basics."""

import pytest

from replay.replay_environment import ReplayEnvironment
from replay.mock_environment import MockEnvironment
from stateguard.interfaces.action import Action


def make_records():
    return [
        {"step": 1, "proposal": {"subgoal_id": "S1"},
         "observation_before": {"step": 0, "snapshot": {"x": None}},
         "observation_after": {"step": 1, "snapshot": {"x": 1}}},
        {"step": 2, "proposal": {"subgoal_id": "S2"},
         "observation_before": {"step": 1, "snapshot": {"x": 1}},
         "observation_after": {"step": 2, "snapshot": {"x": 2}}},
    ]


def test_replay_reset_observe_step():
    env = ReplayEnvironment(make_records())
    obs = env.reset()
    assert obs.get("x") is None  # first record's observation_before
    obs = env.step(Action("next"))
    assert obs.get("x") == 1
    obs = env.step(Action("next"))
    assert obs.get("x") == 2
    assert obs.step == 2
    with pytest.raises(RuntimeError):
        env.step(Action("next"))


def test_replay_load_jsonl(tmp_path):
    p = tmp_path / "traj.jsonl"
    p.write_text('{"step": 1, "proposal": {}, "observation_before": {}, '
                 '"observation_after": {"step": 1, "snapshot": {"y": 7}}}\n')
    env = ReplayEnvironment.load(str(p))
    env.reset()
    assert env.step(Action("next")).get("y") == 7


def test_replay_fault_splice():
    env = ReplayEnvironment(make_records())
    env.fault_at(0, {"x": "CORRUPTED"})
    env.reset()
    assert env.step(Action("next")).get("x") == "CORRUPTED"


def test_mock_environment_actions():
    spec = {
        "state": {"otp": None, "email": None, "form": {}, "submitted": False},
        "actions": {
            "read_otp": {"params": [], "effect": {"otp": 483921}},
            "fill_form": {"params": ["otp", "email"],
                          "effect": {"form.otp": "@otp", "form.email": "@email"}},
            "submit": {"params": [], "effect": {"submitted": True}},
        },
    }
    env = MockEnvironment(spec)
    obs = env.reset()
    obs = env.step(Action("read_otp"))
    assert obs.get("otp") == 483921
    obs = env.step(Action("fill_form", {"otp": 483921, "email": "a@b.c"}))
    assert obs.get("form.email") == "a@b.c"
    obs = env.step(Action("submit"))
    assert obs.get("submitted") is True


def test_mock_environment_not_persisted_temp_target():
    spec = {"state": {"saved": None},
            "actions": {"save": {"params": ["v"],
                                 "effect": {"__temp__.saved": "@v"}}}}
    env = MockEnvironment(spec)
    env.step(Action("save", {"v": "x"}))
    obs = env.observe()
    assert obs.get("saved") is None  # not in the persisted state


def test_mock_environment_fix_action():
    spec = {"state": {"sheet": None},
            "actions": {"select": {"params": ["sheet"],
                                   "effect": {"sheet": "WRONG_TARGET"}}}}
    env = MockEnvironment(spec)
    env.step(Action("select", {"sheet": "Sheet2"}))
    assert env.observe().get("sheet") == "WRONG_TARGET"
    env.fix_action("select", {"sheet": "@sheet"})
    env.step(Action("select", {"sheet": "Sheet2"}))
    assert env.observe().get("sheet") == "Sheet2"
