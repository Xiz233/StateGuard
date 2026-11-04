from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ModelConfigError


@dataclass
class ModelProviderConfig:
    provider_id: str
    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: int = 180
    max_retries: int = 3
    temperature: float = 0.0
    max_tokens: int | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    type: str = "openai_compatible"


def _expand(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"\$\{([^}]+)\}", lambda m: os.getenv(m.group(1), ""), value)


def load_model_config(path: str | Path) -> dict[str, ModelProviderConfig]:
    try:
        import yaml
    except ImportError as exc:
        raise ModelConfigError("PyYAML is required to load model configuration") from exc
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    providers = {}
    for provider_id, raw in data.get("providers", {}).items():
        raw = {k: _expand(v) for k, v in raw.items()}
        providers[provider_id] = ModelProviderConfig(provider_id=provider_id, **raw)
    return providers
