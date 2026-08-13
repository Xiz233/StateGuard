"""Generic Action: name + kwargs. Synthetic tasks are symbolic, so a
name/params pair is the whole action (指引.txt §14 keeps action: Any)."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Action:
    name: str
    params: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        self.params = dict(self.params or {})

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        return cls(d["name"], d.get("params", {}))
