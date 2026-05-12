"""Abstract base classes for embedding and chat providers."""

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Base exception for all provider errors."""
    pass


class RateLimitError(ProviderError):
    """Raised when the provider returns a rate-limit response."""
    pass


class EmbeddingBatchError(ProviderError):
    """Raised when a batch embedding API call fails entirely.

    The ``partial_results`` attribute contains the results that were
    successfully computed before the failure (typically all ``None``).
    """

    def __init__(
        self,
        message: str,
        partial_results: list[list[float] | None] | None = None,
    ) -> None:
        self.partial_results = partial_results
        super().__init__(message)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

EMBEDDING_SUB_BATCH_SIZE: int = 8
"""Maximum number of texts to send in a single provider API call.

Reduced from 100 to 8 for bge-m3 on 4GB VRAM. Sending too many texts at
once causes Ollama to run out of CUDA memory. Each text produces a 1024-dim
embedding vector; 8 texts per batch keeps peak VRAM usage well within 4GB.
"""


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

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ):
        """Stream a chat completion response token by token.

        This is an optional method. The default implementation falls back to
        calling :meth:`chat` and yielding the full response as a single token.

        Subclasses that support streaming should override this to yield
        ``(token_text, is_last)`` tuples, where ``is_last`` is ``True`` only
        for the final yield (which should include the token_usage dict).

        Yields:
            ``(token_text: str, is_last: bool, metadata: dict | None)`` tuples.
            When ``is_last`` is ``True``, ``metadata`` contains ``token_usage``.
            Otherwise ``metadata`` is ``None``.
        """
        result = self.chat(messages, max_tokens=max_tokens, model=model)
        yield result["content"], True, {"token_usage": result["token_usage"]}
