"""A benchmark-neutral bundle of evidence collected after an action."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(frozen=True)
class ObservationBundle:
    step: int = 0
    timestamp: float = field(default_factory=time)
    screenshot: Any = None
    accessibility_tree: Any = None
    structured_state: Any = None
    app_state: Any = None
    clipboard: Any = None
    external_state: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_observation(cls, observation: Any) -> "ObservationBundle":
        metadata = dict(getattr(observation, "metadata", {}) or {})
        return cls(
            step=int(getattr(observation, "step", 0)),
            screenshot=getattr(observation, "screenshot", None),
            accessibility_tree=getattr(observation, "ui_tree", None),
            structured_state=getattr(observation, "structured_state", None),
            app_state={"active_app": getattr(observation, "active_app", None)},
            clipboard=metadata.get("clipboard"),
            external_state=metadata.get("external_state"),
            metadata=metadata,
        )

    def value_for_source(self, source: str) -> Any:
        field_name = {
            "screenshot": "screenshot",
            "accessibility_tree": "accessibility_tree",
            "structured_state": "structured_state",
            "app_state": "app_state",
            "clipboard": "clipboard",
            "external_tool": "external_state",
        }.get(str(source))
        return getattr(self, field_name) if field_name else None
