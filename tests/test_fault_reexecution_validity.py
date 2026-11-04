from stateguard.runtime.episode_runner import EpisodeRunner


def test_nearby_repeat_click_is_compensating_reexecution():
    original = {"type": "click", "x": 1291, "y": 874}
    retry = {"type": "click", "x": 1295, "y": 872}
    unrelated = {"type": "click", "x": 1190, "y": 699}
    assert EpisodeRunner._same_intended_action(original, retry)
    assert not EpisodeRunner._same_intended_action(original, unrelated)


def test_text_reexecution_requires_original_value():
    original = {"type": "type", "text": "expected"}
    assert EpisodeRunner._same_intended_action(
        original, {"type": "type", "text": "expected"})
    assert not EpisodeRunner._same_intended_action(
        original, {"type": "type", "text": "wrong"})
