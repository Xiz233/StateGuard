from types import SimpleNamespace

from stateguard.guard.backends.hybrid_backend import HybridBackend


class Backend:
    def __init__(self, value): self.value = value; self.calls = 0
    def verify(self, *args): self.calls += 1; return self.value


def test_hybrid_falls_back_only_on_unknown():
    rule, mllm = Backend(SimpleNamespace(judgement="unknown")), Backend(SimpleNamespace(judgement="verified"))
    state = SimpleNamespace(get=lambda _: SimpleNamespace(structured_predicate={}, expected_effect={"x": 1}))
    assert HybridBackend(rule, mllm).verify(state, None, SimpleNamespace(subgoal_id="S1"), None).judgement == "verified"
    assert rule.calls == mllm.calls == 1
