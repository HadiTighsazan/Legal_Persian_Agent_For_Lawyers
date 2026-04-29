"""Provider registry and factory functions."""

from typing import TypeVar

from providers.base import BaseEmbeddingProvider, BaseChatProvider

T = TypeVar("T")


class ProviderNotRegisteredError(Exception):
    """Raised when a requested provider is not registered."""
    pass


_embedding_providers: dict[str, type[BaseEmbeddingProvider]] = {}
_chat_providers: dict[str, type[BaseChatProvider]] = {}


def register_embedding_provider(name: str, cls: type[BaseEmbeddingProvider]) -> None:
    """Register an embedding provider class under the given name."""
    _embedding_providers[name] = cls


def register_chat_provider(name: str, cls: type[BaseChatProvider]) -> None:
    """Register a chat provider class under the given name."""
    _chat_providers[name] = cls


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Instantiate and return the configured embedding provider."""
    from django.conf import settings

    name = settings.EMBEDDING_PROVIDER
    cls = _embedding_providers.get(name)
    if cls is None:
        raise ProviderNotRegisteredError(
            f"Embedding provider '{name}' not registered. "
            f"Available: {list(_embedding_providers.keys())}"
        )
    return cls()


def get_chat_provider() -> BaseChatProvider:
    """Instantiate and return the configured chat provider."""
    from django.conf import settings

    name = settings.CHAT_PROVIDER
    cls = _chat_providers.get(name)
    if cls is None:
        raise ProviderNotRegisteredError(
            f"Chat provider '{name}' not registered. "
            f"Available: {list(_chat_providers.keys())}"
        )
    return cls()
