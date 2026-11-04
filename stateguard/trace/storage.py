from __future__ import annotations

import json
from pathlib import Path

from .models import ExecutionTraceEntry


class TraceStorage:
    def __init__(self, path=None, max_entries: int = 200):
        self.path = Path(path) if path else None
        self.max_entries = max(1, int(max_entries))
        self.entries: list[ExecutionTraceEntry] = []

    def append(self, entry: ExecutionTraceEntry) -> None:
        self.entries.append(entry)
        self.entries = self.entries[-self.max_entries:]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                "".join(json.dumps(item.to_dict(), default=str) + "\n"
                        for item in self.entries), encoding="utf-8")

    def recent(self, limit: int | None = None) -> list[ExecutionTraceEntry]:
        return self.entries[-limit:] if limit else list(self.entries)
