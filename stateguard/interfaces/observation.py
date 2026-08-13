"""Provider-neutral symbolic or multimodal observation."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(init=False)
class Observation:
    step: int
    screenshot: str | bytes | None
    structured_state: dict | None
    ui_tree: dict | list | str | None
    visible_text: str | None
    active_app: str | None
    metadata: dict

    def __init__(self, snapshot: dict | None = None, step: int = 0, *,
                 screenshot: str | bytes | None = None,
                 structured_state: dict | None = None,
                 ui_tree: dict | list | str | None = None,
                 visible_text: str | None = None,
                 active_app: str | None = None,
                 metadata: dict | None = None):
        self.step = step
        self.screenshot = screenshot
        self.structured_state = structured_state if structured_state is not None else snapshot
        self.ui_tree = ui_tree
        self.visible_text = visible_text
        self.active_app = active_app
        self.metadata = dict(metadata or {})

    @property
    def snapshot(self) -> dict:
        return self.structured_state or {}

    def get(self, path: str) -> Any:
        return get_path(self.snapshot, path)

    def to_dict(self) -> dict:
        return {"step": self.step, "screenshot": self.screenshot,
                "structured_state": self.structured_state, "ui_tree": self.ui_tree,
                "visible_text": self.visible_text, "active_app": self.active_app,
                "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        if "structured_state" not in d and "snapshot" in d:
            return cls(d["snapshot"], d.get("step", 0))
        return cls(step=d.get("step", 0), screenshot=d.get("screenshot"),
                   structured_state=d.get("structured_state"), ui_tree=d.get("ui_tree"),
                   visible_text=d.get("visible_text"), active_app=d.get("active_app"),
                   metadata=d.get("metadata"))

    @property
    def ref(self) -> str:
        return f"obs@{self.step}"
