"""Provider abstraction layer for embedding and chat/LLM providers."""

# Trigger provider registration on import (embedding + chat providers)
import providers.registration  # noqa: F401

from providers.base import BaseEmbeddingProvider, BaseChatProvider
from providers.registry import (
    ProviderNotRegisteredError,
    register_embedding_provider,
    register_chat_provider,
    get_embedding_provider,
    get_chat_provider,
)

__all__ = [
    "BaseEmbeddingProvider",
    "BaseChatProvider",
    "ProviderNotRegisteredError",
    "register_embedding_provider",
    "register_chat_provider",
    "get_embedding_provider",
    "get_chat_provider",
]
