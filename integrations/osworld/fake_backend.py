from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .adapter import EvaluationResult


class FakeOSWorldBackend:
    """Deterministic GUI plumbing backend; never used for research scores."""
    def __init__(self, screenshot_dir: str | None = None):
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.task, self.state, self.step = {}, {}, 0

    def reset(self, task_spec):
        self.task, self.state, self.step = task_spec, deepcopy(task_spec.get("initial_state", {})), 0
        return self.get_observation()

    def get_observation(self):
        return {"structured_state": deepcopy(self.state),
                "visible_text": "; ".join(f"{k}={v}" for k, v in sorted(self.state.items())),
                "active_app": self.task.get("app", "fake"),
                "screenshot": self._screenshot(), "metadata": {"fake": True}}

    def execute_action(self, action):
        self.step += 1
        for rule in self.task.get("action_rules", []):
            if all(action.get(k) == v for k, v in rule.get("match", {}).items()):
                self.state.update(deepcopy(rule.get("effect", {})))
                break
        return self.get_observation()

    def evaluate(self, task_spec):
        expected = task_spec.get("success_state", {})
        success = all(self.state.get(k) == v for k, v in expected.items())
        return EvaluationResult(success, float(success), {"state": deepcopy(self.state)})

    def close(self): pass
    def health_check(self): return True
    def backend_info(self): return {"name": "fake", "version": "1"}

    def _screenshot(self):
        if not self.screenshot_dir:
            return None
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshot_dir / f"step_{self.step:04d}.png"
        # Valid 1x1 transparent PNG, sufficient to exercise image plumbing.
        path.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"))
        return str(path)
