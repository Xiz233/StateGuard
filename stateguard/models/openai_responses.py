from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
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
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _response_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", ()):
        if item.get("type") != "message":
            continue
        for content in item.get("content", ()):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)


class OpenAIResponsesModelClient(MultimodalModelClient):
    """OpenAI Responses API client with OpenCode Go session routing."""

    def __init__(self, config: ModelProviderConfig, opener=None, sleep=time.sleep,
                 session_id: str | None = None):
        self.config = config
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep
        self.session_id = session_id or str(uuid.uuid4())

    def generate(self, messages, images=None, response_schema=None) -> ModelResponse:
        key = os.getenv(self.config.api_key_env)
        if not key:
            raise ModelConfigError(
                f"missing credential environment variable {self.config.api_key_env}")
        payload_messages = [dict(message) for message in messages]
        if images:
            last = payload_messages[-1]
            content = last["content"]
            parts = (content if isinstance(content, list)
                     else [{"type": "input_text", "text": content}])
            parts += [{"type": "input_image", "image_url": _image_url(image)}
                      for image in images]
            last["content"] = parts
        if response_schema is not None:
            payload_messages[-1] = dict(payload_messages[-1])
            content = payload_messages[-1]["content"]
            suffix = "Return one valid JSON object only."
            if isinstance(content, str):
                payload_messages[-1]["content"] = f"{content}\n\n{suffix}"
            else:
                payload_messages[-1]["content"] = [
                    *content, {"type": "input_text", "text": suffix}]
        # OpenCode's GPT Responses models currently reject `temperature`.
        payload = {"model": self.config.model, "input": payload_messages}
        if self.config.max_tokens is not None:
            payload["max_output_tokens"] = self.config.max_tokens

        started, error, attempts = time.monotonic(), None, []
        for attempt in range(self.config.max_retries):
            request = urllib.request.Request(
                self.config.base_url.rstrip("/") + "/responses",
                data=json.dumps(payload).encode(), method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "StateGuard/1.0",
                    "x-opencode-session": self.session_id,
                    **self.config.extra_headers,
                })
            try:
                attempt_started = time.monotonic()
                with self.opener(request, timeout=self.config.timeout_seconds) as response:
                    raw = json.loads(response.read())
                text = _response_text(raw)
                if not text:
                    raise ModelResponseError("model returned empty content")
                parsed = parse_json(text) if response_schema is not None else None
                attempts.append({"attempt": attempt + 1, "status": "completed",
                                 "request_delta": None,
                                 "latency_seconds": time.monotonic() - attempt_started})
                return ModelResponse(
                    text, parsed, raw.get("model", self.config.model),
                    raw.get("usage"), time.monotonic() - started, raw, attempts)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                error = f"HTTP {exc.code} {exc.reason}: {body[:2000]}"
                attempts.append({"attempt": attempt + 1, "status": "failed",
                                 "request_delta": None,
                                 "error": error})
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError,
                    json.JSONDecodeError, ModelResponseError) as exc:
                error = exc
                attempts.append({"attempt": attempt + 1, "status": "failed",
                                 "request_delta": None,
                                 "error": str(exc)})
            if attempt + 1 < self.config.max_retries:
                self.sleep(2 ** attempt)
        exc = ModelResponseError(
            f"model request failed after {self.config.max_retries} attempts: {error}")
        exc.attempts = attempts
        raise exc
