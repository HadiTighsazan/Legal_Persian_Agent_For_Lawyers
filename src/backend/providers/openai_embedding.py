"""OpenAI embedding provider — wraps OpenAI Embeddings API."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from providers.base import BaseEmbeddingProvider, EmbeddingBatchError

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Uses OpenAI's Embeddings API (``text-embedding-3-small``, etc.)."""

    def __init__(self) -> None:
        import openai

        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model: str = settings.OPENAI_EMBEDDING_MODEL
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
                "OpenAIEmbeddingProvider.embed: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OpenAIEmbeddingProvider.embed: Failed — %s",
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
                "OpenAIEmbeddingProvider.embed_batch: Generated %d embeddings",
                len(valid_texts),
            )
        except Exception as e:
            logger.error(
                "OpenAIEmbeddingProvider.embed_batch: Failed — %s",
                e,
            )
            raise EmbeddingBatchError(
                f"OpenAI batch embedding failed: {e}",
                partial_results=results,
            ) from e

        return results

    def embed_query(self, text: str) -> list[float]:
        """Embed a query string.

        Raises:
            ValueError: If *text* is empty or whitespace-only.
            Exception: If the OpenAI API call fails.
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
                "OpenAIEmbeddingProvider.embed_query: Generated embedding "
                "(dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OpenAIEmbeddingProvider.embed_query: Failed — %s",
                e,
            )
            raise
