import pytest

from integrations.osworld.action_converter import convert_action
from integrations.osworld.adapter import OSWorldAdapter


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
