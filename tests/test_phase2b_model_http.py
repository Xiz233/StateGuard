import json

import pytest

from stateguard.models.config import ModelProviderConfig
from stateguard.models.errors import ModelResponseError
from stateguard.models.openai_compatible import OpenAICompatibleModelClient
from tests.fake_model_server import FakeModelServer


def reply(content='{"ok": true}'):
    return {"model": "fake", "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def client(url, retries=1):
    return OpenAICompatibleModelClient(ModelProviderConfig("p", url, "fake", "TEST_API_KEY",
                                                           max_retries=retries), sleep=lambda _: None)


def test_real_http_multimodal_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_API_KEY", "secret")
    image = tmp_path / "x.png"; image.write_bytes(b"png")
    with FakeModelServer([(200, reply())]) as server:
        response = client(server.base_url).generate([{"role": "user", "content": "inspect"}],
                                                    [str(image)], {"type": "object"})
        content = server.requests[0]["json"]["messages"][0]["content"]
        assert response.parsed == {"ok": True}
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert server.requests[0]["path"] == "/v1/chat/completions"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_are_explicit(monkeypatch, status):
    monkeypatch.setenv("TEST_API_KEY", "secret")
    with FakeModelServer([(status, {"error": "failed"})]) as server:
        with pytest.raises(ModelResponseError): client(server.base_url).generate([], response_schema={})


@pytest.mark.parametrize("body", [b"not-json", reply(""), reply("not model json")])
def test_bad_responses_are_explicit(monkeypatch, body):
    monkeypatch.setenv("TEST_API_KEY", "secret")
    with FakeModelServer([(200, body)]) as server:
        with pytest.raises(ModelResponseError): client(server.base_url).generate([], response_schema={})


def test_rate_limit_retries(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret")
    with FakeModelServer([(429, {"error": "slow"}), (200, reply())]) as server:
        assert client(server.base_url, 2).generate([], response_schema={}).parsed["ok"]
        assert len(server.requests) == 2


def test_timeout_is_explicit(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret")
    config = ModelProviderConfig("p", "http://unused", "fake", "TEST_API_KEY", max_retries=1)
    timed_out = OpenAICompatibleModelClient(config, opener=lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(ModelResponseError): timed_out.generate([], response_schema={})
