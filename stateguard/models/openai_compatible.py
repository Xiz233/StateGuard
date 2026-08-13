from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .base import ModelResponse, MultimodalModelClient
from .client import parse_json
from .config import ModelProviderConfig
from .errors import ModelConfigError, ModelResponseError


def _image_url(image: str | bytes) -> str:
    if isinstance(image, bytes):
        data, mime = image, "image/png"
    elif image.startswith("data:"):
        return image
    else:
        path = Path(image)
        data, mime = path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class OpenAICompatibleModelClient(MultimodalModelClient):
    def __init__(self, config: ModelProviderConfig, opener=None, sleep=time.sleep):
        self.config, self.opener, self.sleep = config, opener or urllib.request.urlopen, sleep

    def generate(self, messages, images=None, response_schema=None) -> ModelResponse:
        key = os.getenv(self.config.api_key_env)
        if not key:
            raise ModelConfigError(f"missing credential environment variable {self.config.api_key_env}")
        payload_messages = [dict(m) for m in messages]
        if images:
            last = payload_messages[-1]
            content = last["content"]
            parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
            parts += [{"type": "image_url", "image_url": {"url": _image_url(i)}} for i in images]
            last["content"] = parts
        payload = {"model": self.config.model, "messages": payload_messages,
                   "temperature": self.config.temperature}
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        started, error = time.monotonic(), None
        for attempt in range(self.config.max_retries):
            if attempt and response_schema is not None:
                payload["messages"] = payload_messages + [
                    {"role": "user", "content": "Return valid JSON only."}]
            request = urllib.request.Request(
                self.config.base_url.rstrip("/") + "/chat/completions",
                data=json.dumps(payload).encode(), method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         **self.config.extra_headers})
            try:
                with self.opener(request, timeout=self.config.timeout_seconds) as response:
                    raw = json.loads(response.read())
                text = raw["choices"][0]["message"]["content"]
                if not text:
                    raise ModelResponseError("model returned empty content")
                parsed = parse_json(text) if response_schema is not None else None
                return ModelResponse(text, parsed, raw.get("model", self.config.model),
                                     raw.get("usage"), time.monotonic() - started, raw)
            except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError,
                    json.JSONDecodeError, ModelResponseError) as exc:
                error = exc
                if attempt + 1 < self.config.max_retries:
                    self.sleep(2 ** attempt)
        raise ModelResponseError(f"model request failed after {self.config.max_retries} attempts: {error}")
