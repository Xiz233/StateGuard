from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ModelResponse:
    text: str
    parsed: dict | None
    model: str
    usage: dict | None
    latency_seconds: float
    raw_response: dict | None = None
    attempts: list[dict[str, Any]] | None = None


class MultimodalModelClient(ABC):
    @abstractmethod
    def generate(self, messages, images=None, response_schema=None) -> ModelResponse: ...
