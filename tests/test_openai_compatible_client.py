import json
import os

from stateguard.models.config import ModelProviderConfig
from stateguard.models.openai_compatible import OpenAICompatibleModelClient


class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self):
        return json.dumps({"model": "m", "choices": [{"message": {"content": "{\"ok\":true}"}}]}).encode()


def test_openai_compatible_parses_json(monkeypatch):
    monkeypatch.setenv("KEY", "secret")
    client = OpenAICompatibleModelClient(ModelProviderConfig("p", "http://x/v1", "m", "KEY"),
                                         opener=lambda *a, **k: Response())
    assert client.generate([{"role": "user", "content": "x"}], response_schema={}).parsed["ok"]
