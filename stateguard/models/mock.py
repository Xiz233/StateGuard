from __future__ import annotations

import json

from .base import ModelResponse, MultimodalModelClient


class MockModelClient(MultimodalModelClient):
    def __init__(self, responses):
        self.policy = responses if callable(responses) else None
        self.responses = None if self.policy else iter(responses)

    def generate(self, messages, images=None, response_schema=None):
        value = self.policy(messages, images, response_schema) if self.policy else next(self.responses)
        if callable(value):
            value = value(messages, images, response_schema)
        parsed = value if isinstance(value, dict) else None
        text = json.dumps(value) if parsed is not None else value
        return ModelResponse(text, parsed, "mock", None, 0.0, None)
