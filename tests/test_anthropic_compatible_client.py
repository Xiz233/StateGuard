import json

from stateguard.models import AnthropicCompatibleModelClient, create_model_client
from stateguard.models.config import ModelProviderConfig


class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(reply()).encode()


def reply(content='{"judgement":"verified"}'):
    return {"model": "qwen3.7-plus", "content": [{"type": "text", "text": content}],
            "usage": {"input_tokens": 12, "output_tokens": 3}}


def config(url):
    return ModelProviderConfig("guard", url, "qwen3.7-plus", "OPENCODE_GO_API_KEY",
                               max_retries=1, type="anthropic_compatible")


def test_anthropic_multimodal_messages_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "secret")
    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    captured = {}
    def opener(request, **kwargs):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["json"] = json.loads(request.data)
        return Response()
    client = AnthropicCompatibleModelClient(config("https://example/v1"), opener=opener)
    response = client.generate([{"role": "user", "content": "inspect"}],
                               [str(image)], {"type": "object"})
    blocks = captured["json"]["messages"][0]["content"]
    assert captured["url"] == "https://example/v1/messages"
    assert captured["headers"]["X-api-key"] == "secret"
    assert blocks[0] == {"type": "text", "text": "inspect"}
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert response.parsed == {"judgement": "verified"}
    assert response.usage["prompt_tokens"] == 12
    assert response.usage["completion_tokens"] == 3


def test_factory_selects_anthropic_client():
    assert isinstance(create_model_client(config("http://unused")),
                      AnthropicCompatibleModelClient)
