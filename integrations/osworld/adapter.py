from __future__ import annotations

from stateguard.interfaces.environment import EnvironmentAdapter

from .action_converter import convert_action
from .observation_converter import convert_observation


class OSWorldAdapter(EnvironmentAdapter):
    """Thin wrapper; importing this module never imports desktop_env."""
    def __init__(self, env=None):
        if env is None:
            try:
                import desktop_env
            except ImportError as exc:
                raise RuntimeError("OSWorld is not installed") from exc
            env = desktop_env.DesktopEnv()
        self.env, self._step = env, 0

    def reset(self, task=None):
        self._step = 0
        return convert_observation(self.env.reset(task) if task is not None else self.env.reset())

    def observe(self):
        return convert_observation(self.env.observe(), self._step)

    def step(self, action):
        self._step += 1
        return convert_observation(self.env.step(convert_action(action)), self._step)

    def evaluate(self):
        return self.env.evaluate()
