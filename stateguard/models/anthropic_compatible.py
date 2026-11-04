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


def _image_block(image: str | bytes) -> dict:
    if isinstance(image, bytes):
        data, media_type = image, "image/png"
    elif image.startswith("data:"):
        header, encoded = image.split(",", 1)
        media_type = header.split(";", 1)[0].removeprefix("data:")
        return {"type": "image", "source": {"type": "base64",
                "media_type": media_type, "data": encoded}}
    else:
        path = Path(image)
        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64",
            "media_type": media_type, "data": base64.b64encode(data).decode()}}


class AnthropicCompatibleModelClient(MultimodalModelClient):
    def __init__(self, config: ModelProviderConfig, opener=None, sleep=time.sleep):
        self.config, self.opener, self.sleep = config, opener or urllib.request.urlopen, sleep

    def generate(self, messages, images=None, response_schema=None) -> ModelResponse:
        key = os.getenv(self.config.api_key_env)
        if not key:
            raise ModelConfigError(f"missing credential environment variable {self.config.api_key_env}")
        system, payload_messages = [], []
        for message in messages:
            if message["role"] == "system":
                system.append(str(message["content"]))
                continue
            content = message["content"]
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            payload_messages.append({"role": message["role"], "content": list(blocks)})
        if not payload_messages:
            payload_messages.append({"role": "user", "content": [{"type": "text", "text": ""}]})
        if images:
            payload_messages[-1]["content"].extend(_image_block(image) for image in images)
        payload = {"model": self.config.model, "messages": payload_messages,
                   "max_tokens": self.config.max_tokens or 4096,
                   "temperature": self.config.temperature}
        if system:
            payload["system"] = "\n\n".join(system)
        started, error, attempts = time.monotonic(), None, []
        for attempt in range(self.config.max_retries):
            attempt_payload = dict(payload)
            request_delta = None
            if attempt and response_schema is not None:
                request_delta = {"append_messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Return valid JSON only."}]}]}
                attempt_payload["messages"] = (
                    payload_messages + request_delta["append_messages"])
            request = urllib.request.Request(
                self.config.base_url.rstrip("/") + "/messages",
                data=json.dumps(attempt_payload).encode(), method="POST",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json", **self.config.extra_headers})
            try:
                attempt_started = time.monotonic()
                with self.opener(request, timeout=self.config.timeout_seconds) as response:
                    raw = json.loads(response.read())
                text = "".join(block.get("text", "") for block in raw.get("content", [])
                               if block.get("type") == "text")
                if not text:
                    raise ModelResponseError("model returned empty content")
                parsed = parse_json(text) if response_schema is not None else None
                usage = raw.get("usage") or {}
                normalized_usage = {**usage,
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0)}
                attempts.append({"attempt": attempt + 1, "status": "completed",
                                 "request_delta": request_delta,
                                 "latency_seconds": time.monotonic() - attempt_started})
                return ModelResponse(text, parsed, raw.get("model", self.config.model),
                                     normalized_usage, time.monotonic() - started, raw,
                                     attempts)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError,
                    json.JSONDecodeError, ModelResponseError) as exc:
                error = exc
                attempts.append({"attempt": attempt + 1, "status": "failed",
                                 "request_delta": request_delta,
                                 "error": str(exc)})
                if attempt + 1 < self.config.max_retries:
                    self.sleep(2 ** attempt)
        exc = ModelResponseError(
            f"model request failed after {self.config.max_retries} attempts: {error}")
        exc.attempts = attempts
        raise exc
