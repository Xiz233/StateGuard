import json

from stateguard.models import OpenAIResponsesModelClient, create_model_client
from stateguard.models.config import ModelProviderConfig


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps({
            "model": "gpt-5.6-luna",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": '{"ok": true}'}],
            }],
            "usage": {"input_tokens": 2, "output_tokens": 4},
        }).encode()


def _config():
    return ModelProviderConfig(
        "luna", "https://example/v1", "gpt-5.6-luna", "KEY",
        max_retries=1, max_tokens=256, type="openai_responses")


def test_responses_client_uses_session_header_and_multimodal_payload(
        monkeypatch, tmp_path):
    monkeypatch.setenv("KEY", "secret")
    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    captured = {}

    def opener(request, **_kwargs):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["json"] = json.loads(request.data)
        return Response()

    client = OpenAIResponsesModelClient(
        _config(), opener=opener, session_id="stable-session")
    result = client.generate(
        [{"role": "user", "content": "inspect"}], [str(image)], {})

    assert captured["url"] == "https://example/v1/responses"
    assert captured["headers"]["X-opencode-session"] == "stable-session"
    assert captured["headers"]["User-agent"] == "StateGuard/1.0"
    assert captured["json"]["max_output_tokens"] == 256
    assert "temperature" not in captured["json"]
    assert captured["json"]["input"][0]["content"][1]["type"] == "input_image"
    assert result.parsed == {"ok": True}


def test_factory_selects_responses_client():
    assert isinstance(create_model_client(_config()), OpenAIResponsesModelClient)
