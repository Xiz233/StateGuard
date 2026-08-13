"""EnvironmentAdapter: the generic seam between StateGuard and any
benchmark environment (OSWorld / AndroidWorld / mock / replay).

benchmark-specific code must live in integrations/ and only speak this
interface (指引.txt §35)."""

from __future__ import annotations

import abc

from .observation import Observation
from .action import Action


class EnvironmentAdapter(abc.ABC):
    @abc.abstractmethod
    def reset(self) -> Observation: ...

    @abc.abstractmethod
    def observe(self) -> Observation: ...

    @abc.abstractmethod
    def step(self, action: Action) -> Observation: ...
