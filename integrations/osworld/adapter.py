from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from stateguard.interfaces.environment import EnvironmentAdapter

from .action_converter import convert_action
from .observation_converter import convert_observation


@dataclass
class EvaluationResult:
    success: bool
    score: float = 0.0
    details: dict | None = None


@runtime_checkable
class OSWorldBackendProtocol(Protocol):
    def reset(self, task_spec: dict) -> dict: ...
    def get_observation(self) -> dict: ...
    def execute_action(self, action: dict) -> dict: ...
    def evaluate(self, task_spec: dict) -> EvaluationResult | dict: ...
    def close(self) -> None: ...
    def health_check(self) -> bool: ...
    def backend_info(self) -> dict: ...


class DesktopEnvBackend:
    """The only version-sensitive OSWorld seam."""
    def __init__(self, **kwargs):
        try:
            from desktop_env.envs.desktop_env import DesktopEnv
        except ImportError as exc:
            raise RuntimeError("OSWorld is not installed") from exc
        self.env = DesktopEnv(**kwargs)

    def reset(self, task_spec): return self.env.reset(task_spec)
    def get_observation(self): return self.env._get_obs()
    def execute_action(self, action): return self.env.step(action)
    def evaluate(self, task_spec): return self.env.evaluate()
    def close(self): self.env.close()
    def health_check(self): return True
    def backend_info(self): return {"name": "desktop_env"}


class OSWorldAdapter(EnvironmentAdapter):
    def __init__(self, backend: OSWorldBackendProtocol | None = None, screen_size=(1920, 1080),
                 **backend_kwargs):
        self.backend = backend or DesktopEnvBackend(**backend_kwargs)
        self.screen_size, self._step, self._task = screen_size, 0, None

    def reset(self, task_spec=None):
        self._step, self._task = 0, task_spec or {}
        try:
            raw = self.backend.reset(self._task)
        except TypeError:
            raw = self.backend.reset()
        return convert_observation(raw, self._step)

    def observe(self):
        observe = getattr(self.backend, "get_observation", None) or self.backend.observe
        return convert_observation(observe(), self._step)

    def step(self, action):
        self._step += 1
        execute = getattr(self.backend, "execute_action", None) or self.backend.step
        return convert_observation(execute(convert_action(action, self.screen_size)), self._step)

    def evaluate(self, task_spec=None):
        try:
            result = self.backend.evaluate(task_spec or self._task)
        except TypeError:
            result = self.backend.evaluate()
        return result if isinstance(result, EvaluationResult) else EvaluationResult(**result)

    def close(self):
        if hasattr(self.backend, "close"): self.backend.close()
    def health_check(self): return self.backend.health_check() if hasattr(self.backend, "health_check") else True
    def backend_info(self): return self.backend.backend_info() if hasattr(self.backend, "backend_info") else {"name": type(self.backend).__name__}

    def note_fault_injection(self, event, spec):
        if hasattr(self.backend, "note_fault_injection"):
            self.backend.note_fault_injection(event, spec)

    def expose_failure(self, event):
        if hasattr(self.backend, "expose_failure"):
            self.backend.expose_failure(event)
        return self.observe()
