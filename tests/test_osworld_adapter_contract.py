import pytest

from integrations.osworld.action_converter import convert_action
from integrations.osworld.adapter import EvaluationResult, OSWorldAdapter
from integrations.osworld.observation_converter import convert_observation
from stateguard.verification.contracts import EvidenceSource


class Env:
    def reset(self, task=None): return {"visible_text": "ready"}
    def observe(self): return {"visible_text": "ready"}
    def step(self, action): return {"visible_text": action["type"]}
    def evaluate(self): return {"ok": True}


def test_adapter_without_osworld_dependency():
    adapter = OSWorldAdapter(Env())
    assert adapter.reset().visible_text == "ready"
    assert adapter.step({"type": "wait"}).step == 1
    with pytest.raises(ValueError): convert_action({"type": "unknown"})


def test_adapter_capabilities_follow_observation_channels():
    adapter = OSWorldAdapter(Env())
    observation = convert_observation({
        "screenshot": b"png",
        "accessibility_tree": {"role": "window"},
        "structured_state": {"ready": True},
    })
    capabilities = adapter.get_capabilities(observation)
    assert EvidenceSource.SCREENSHOT in capabilities.available_sources
    assert EvidenceSource.ACCESSIBILITY_TREE in capabilities.available_sources
    assert EvidenceSource.STRUCTURED_STATE in capabilities.available_sources
    bundle = adapter.collect_observation_bundle(observation)
    assert bundle.accessibility_tree == {"role": "window"}
    assert bundle.structured_state == {"ready": True}


def test_real_osworld_action_conversion():
    assert convert_action({"type": "wait"}, action_format="pyautogui") == "WAIT"
    click = convert_action({"type": "click", "x": 12, "y": 34},
                           (100, 100), "pyautogui")
    assert click == "import pyautogui; pyautogui.click(12, 34)"
    double_click = convert_action(
        {"type": "double_click", "x": 12, "y": 34},
        (100, 100), "pyautogui")
    assert "clicks=2" in double_click
    assert "button='left'" in double_click
    right_click = convert_action(
        {"type": "right-click", "x": 12, "y": 34},
        (100, 100), "generic")
    assert right_click == {"type": "click", "x": 12, "y": 34, "button": "right"}
    typed = convert_action({"type": "type", "text": "O'Reilly"},
                           action_format="pyautogui")
    assert "pyautogui.write(\"O'Reilly\", interval=0.01)" in typed
    unicode_typed = convert_action({"type": "type", "text": "你好"},
                                   action_format="pyautogui")
    assert "pyperclip.copy('你好')" in unicode_typed
    hotkey = convert_action({"type": "hotkey", "keys": ["CTRL", "S"]},
                            action_format="pyautogui")
    assert "pyautogui.hotkey('ctrl', 's')" in hotkey


def test_real_osworld_step_tuple_and_numeric_evaluation():
    class RealishEnv:
        def reset(self, task=None):
            return {"screenshot": b"png", "accessibility_tree": "tree"}
        def get_observation(self): return {"screenshot": b"png"}
        def execute_action(self, action):
            assert action["type"] == "click"
            return ({"screenshot": b"after"}, 0, False, {"source": "test"})
        def evaluate(self, task=None): return 0.5
        def backend_info(self): return {"action_format": "generic"}

    adapter = OSWorldAdapter(RealishEnv(), (100, 100))
    assert adapter.reset({}).ui_tree == "tree"
    after = adapter.step({"type": "click", "x": 1, "y": 2})
    assert after.metadata == {"reward": 0, "done": False, "info": {"source": "test"}}
    assert adapter.evaluate() == EvaluationResult(True, 0.5, None)


def test_observation_rejects_invalid_step_contract():
    with pytest.raises(ValueError):
        convert_observation(({}, 0, False))


def test_reset_waits_for_nonblank_screen(monkeypatch):
    class RecoveringBackend:
        observations = iter([{"screenshot": b"blank"}, {"screenshot": b"ready"}])

        def reset(self, task=None):
            return {"screenshot": b"blank"}

        def get_observation(self):
            return next(self.observations)

    monkeypatch.setattr("integrations.osworld.adapter.time.sleep", lambda _: None)
    monkeypatch.setattr(OSWorldAdapter, "_screen_is_usable",
                        staticmethod(lambda obs: obs.screenshot == b"ready"))
    adapter = OSWorldAdapter(RecoveringBackend(), reset_ready_timeout_seconds=1,
                             reset_poll_seconds=0.01)
    assert adapter.reset().screenshot == b"ready"


def test_reset_rejects_persistent_blank_screen(monkeypatch):
    class BlankBackend:
        def reset(self, task=None):
            return {"screenshot": b"blank"}

        def get_observation(self):
            return {"screenshot": b"blank"}

    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr("integrations.osworld.adapter.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("integrations.osworld.adapter.time.sleep", lambda _: None)
    monkeypatch.setattr(OSWorldAdapter, "_screen_is_usable", staticmethod(lambda obs: False))
    adapter = OSWorldAdapter(BlankBackend(), reset_ready_timeout_seconds=1,
                             reset_poll_seconds=0.01)
    with pytest.raises(RuntimeError, match="remained blank"):
        adapter.reset()
