from types import SimpleNamespace

from stateguard.runtime.episode_runner import EpisodeRunner


def test_unknown_budget_action_equivalence_supports_multiaction_progress():
    actions = [
        {"type": "hotkey", "keys": ["ctrl", "alt", "t"]},
        {"type": "type", "text": "write file"},
        {"type": "hotkey", "keys": ["enter"]},
        {"type": "type", "text": "cat output.txt"},
    ]
    assert all(not EpisodeRunner._same_intended_action(current, previous)
               for previous, current in zip(actions, actions[1:]))


def test_unknown_budget_recognizes_repeated_scroll_loop():
    first = {"type": "scroll", "dx": 0, "dy": -500}
    second = {"type": "scroll", "dx": 0, "dy": -500}
    assert EpisodeRunner._same_intended_action(first, second)
