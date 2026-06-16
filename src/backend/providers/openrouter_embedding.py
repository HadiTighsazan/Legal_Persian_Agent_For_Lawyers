"""OpenRouter embedding provider — wraps OpenRouter Embeddings API.

OpenRouter provides an OpenAI-compatible embedding API, so we use the
``openai`` Python client pointed at OpenRouter's base URL
(``https://openrouter.ai/api/v1``). This lets us use embedding models
like ``bge-m3``, ``text-embedding-3-small``, and others available on
the OpenRouter platform.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from httpx import Client, Timeout

from providers.base import BaseEmbeddingProvider, EmbeddingBatchError

logger = logging.getLogger(__name__)


class OpenRouterEmbeddingProvider(BaseEmbeddingProvider):
    """Uses OpenRouter API for embeddings (``bge-m3``, etc.).

    Reads ``OPENROUTER_API_KEY``, ``OPENROUTER_BASE_URL``, and
    ``OPENROUTER_EMBEDDING_MODEL`` from Django settings. Supports both
    single-text and batch embedding via the OpenAI-compatible API.
    """

    def __init__(self) -> None:
        import openai

        # Configure HTTP client with timeouts to prevent hanging on
        # DNS resolution failures or unresponsive APIs.
        http_client = Client(
            timeout=Timeout(
                connect=10.0,   # Max seconds to wait for connection
                read=60.0,      # Max seconds to wait for response
                write=30.0,     # Max seconds to send request
                pool=10.0,      # Max seconds to wait for connection pool
            ),
        )

        self.client = openai.OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            http_client=http_client,
        )
        self.model: str = settings.OPENROUTER_EMBEDDING_MODEL
        self._dimensions: int = settings.EMBEDDING_DIMENSION

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dimensions(self) -> int:
        return self._dimensions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float] | None:
        """Embed a single text string.

        Returns ``None`` if the text is empty or an API error occurs.
        """
        if not text or not text.strip():
            return None

        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            embedding: list[float] = response.data[0].embedding
            logger.info(
                "OpenRouterEmbeddingProvider.embed: Generated embedding "
                "(dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OpenRouterEmbeddingProvider.embed: Failed — %s",
                e,
            )
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of texts.

        Results are returned in the same order as the input list.  Items that
        fail (empty text, API error) get ``None`` at the corresponding position.
        """
        results: list[list[float] | None] = [None] * len(texts)

        # Pre-fill None for empty texts
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if not t or not t.strip():
                results[i] = None
            else:
                valid_indices.append(i)
                valid_texts.append(t)

        if not valid_texts:
            return results

        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=valid_texts,
            )
            for resp_idx, data_item in enumerate(response.data):
                original_idx = valid_indices[resp_idx]
                results[original_idx] = data_item.embedding

            logger.info(
                "OpenRouterEmbeddingProvider.embed_batch: Generated %d embeddings",
                len(valid_texts),
            )
        except Exception as e:
            logger.error(
                "OpenRouterEmbeddingProvider.embed_batch: Failed — %s",
                e,
            )
            raise EmbeddingBatchError(
                f"OpenRouter batch embedding failed: {e}",
                partial_results=results,
            ) from e

        return results

    def embed_query(self, text: str) -> list[float]:
        """Embed a query string.

        Raises:
            ValueError: If *text* is empty or whitespace-only.
            Exception: If the OpenRouter API call fails.
        """
        if not text or not text.strip():
            raise ValueError("text must be non-empty")

        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            embedding: list[float] = response.data[0].embedding
            logger.info(
                "OpenRouterEmbeddingProvider.embed_query: Generated embedding "
                "(dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OpenRouterEmbeddingProvider.embed_query: Failed — %s",
                e,
            )
            raise
