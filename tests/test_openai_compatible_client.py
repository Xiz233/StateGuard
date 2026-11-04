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


def test_opencode_chat_client_adds_stable_session_header(monkeypatch):
    monkeypatch.setenv("KEY", "secret")
    captured = []

    def opener(request, **_kwargs):
        captured.append(dict(request.header_items()))
        return Response()

    config = ModelProviderConfig(
        "p", "https://opencode.ai/zen/go/v1", "m", "KEY")
    client = OpenAICompatibleModelClient(
        config, opener=opener, session_id="qwen-session")
    client.generate([{"role": "user", "content": "x"}])
    client.generate([{"role": "user", "content": "y"}])

    assert [headers["X-opencode-session"] for headers in captured] == [
        "qwen-session", "qwen-session"]
