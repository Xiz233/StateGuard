"""Generic Observation: a snapshot dict plus dotted-path access."""

from __future__ import annotations

from typing import Any


def get_path(snapshot: dict, path: str) -> Any:
    """'a.b.c' -> snapshot['a']['b']['c']; missing key -> None."""
    cur: Any = snapshot
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_path(snapshot: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = snapshot
    for part in parts[:-1]:
        if part not in cur or cur[part] is None:
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


class Observation:
    def __init__(self, snapshot: dict, step: int):
        self.snapshot: dict = snapshot
        self.step: int = step

    def get(self, path: str) -> Any:
        return get_path(self.snapshot, path)

    def to_dict(self) -> dict:
        return {"step": self.step, "snapshot": self.snapshot}

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        return cls(d["snapshot"], d.get("step", 0))

    @property
    def ref(self) -> str:
        return f"obs@{self.step}"
