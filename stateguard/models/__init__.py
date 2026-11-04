"""Provider-independent model clients."""

from .base import ModelResponse, MultimodalModelClient
from .anthropic_compatible import AnthropicCompatibleModelClient
from .config import ModelProviderConfig, load_model_config
from .openai_compatible import OpenAICompatibleModelClient
from .openai_responses import OpenAIResponsesModelClient


def create_model_client(config: ModelProviderConfig) -> MultimodalModelClient:
    clients = {
        "openai_compatible": OpenAICompatibleModelClient,
        "openai_responses": OpenAIResponsesModelClient,
        "anthropic_compatible": AnthropicCompatibleModelClient,
    }
    try:
        return clients[config.type](config)
    except KeyError as exc:
        raise ValueError(f"unsupported model provider type {config.type!r}") from exc

__all__ = ["ModelResponse", "MultimodalModelClient", "ModelProviderConfig",
           "AnthropicCompatibleModelClient", "OpenAICompatibleModelClient",
           "OpenAIResponsesModelClient",
           "create_model_client", "load_model_config"]
