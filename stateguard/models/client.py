from __future__ import annotations

import json
import re

from .errors import ModelResponseError


def parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelResponseError(f"model returned malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelResponseError("model JSON response must be an object")
    return value
