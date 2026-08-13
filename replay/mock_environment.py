"""Symbolic MockEnvironment (指引.txt §24): declarative action effects.

Action spec: {"name": {"params": [...], "effect": {"var": literal|"@param"}}}
e.g. fill_form -> {"form.otp": "@otp"}. Fault injection swaps effects;
fix_action() restores the original effect so the repair loop can re-run.
"""

from __future__ import annotations

from copy import deepcopy

from stateguard.interfaces.environment import EnvironmentAdapter
from stateguard.interfaces.action import Action
from stateguard.interfaces.observation import Observation, set_path


class MockEnvironment(EnvironmentAdapter):
    def __init__(self, spec: dict):
        self.spec = spec
        self.state: dict = deepcopy(spec.get("state", {}))
        self._temp: dict = {}
        self._step = 0

    def reset(self) -> Observation:
        self.state = deepcopy(self.spec.get("state", {}))
        self._temp = {}
        self._step = 0
        return self.observe()

    def observe(self) -> Observation:
        return Observation(deepcopy(self.state), self._step)

    def step(self, action: Action) -> Observation:
        handler = self.spec["actions"][action.name]
        for var, expr in handler.get("effect", {}).items():
            # "__temp__." targets model "looks successful, not persisted" (§25)
            target = self._temp if var.startswith("__temp__.") else self.state
            if isinstance(expr, str) and expr.startswith("@"):
                value = action.params[expr[1:]]
            else:
                value = expr
            set_path(target, var.removeprefix("__temp__."), value)
        self._step += 1
        return self.observe()

    def fix_action(self, action_name: str, effect: dict) -> None:
        """Restore a (faulted) action's effect — used by the repair loop."""
        self.spec["actions"][action_name]["effect"] = deepcopy(effect)
