from stateguard.interfaces.observation import Observation


def test_multimodal_and_snapshot_compatibility():
    old = Observation({"a": 1}, 2)
    assert old.snapshot == {"a": 1} and old.get("a") == 1
    obs = Observation(step=3, screenshot="x.png", structured_state={"b": 2},
                      visible_text="hello", active_app="calc")
    assert Observation.from_dict(obs.to_dict()).screenshot == "x.png"
