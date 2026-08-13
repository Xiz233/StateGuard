from __future__ import annotations

import json

from .base import ModelResponse, MultimodalModelClient


class MockModelClient(MultimodalModelClient):
    def __init__(self, responses):
        self.responses = iter(responses)

    def generate(self, messages, images=None, response_schema=None):
        value = next(self.responses)
        parsed = value if isinstance(value, dict) else None
        text = json.dumps(value) if parsed is not None else value
        return ModelResponse(text, parsed, "mock", None, 0.0, None)
