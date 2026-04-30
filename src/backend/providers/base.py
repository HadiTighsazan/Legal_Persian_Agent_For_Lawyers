"""Abstract base classes for embedding and chat providers."""

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Base exception for all provider errors."""
    pass


class RateLimitError(ProviderError):
    """Raised when the provider returns a rate-limit response."""
    pass


class BaseEmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> list[float] | None:
        """Embed a single text. Return None on failure."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of texts. Return list aligned with input."""
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a query. Raise on failure."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimension for this provider."""
        ...


class BaseChatProvider(ABC):
    """Abstract interface for chat/LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Returns dict with keys:
        - content: str
        - token_usage: dict with prompt_tokens, completion_tokens, total_tokens
        """
        ...
