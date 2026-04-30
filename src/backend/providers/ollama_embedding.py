"""Ollama embedding provider — wraps Ollama's /api/embed endpoint."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

from providers.base import BaseEmbeddingProvider, EmbeddingBatchError

logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Uses Ollama's ``/api/embed`` endpoint for embeddings."""

    def __init__(self) -> None:
        self.base_url: str = settings.OLLAMA_BASE_URL
        self.model: str = settings.OLLAMA_EMBEDDING_MODEL
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

        url = f"{self.base_url}/api/embed"

        try:
            response = requests.post(
                url,
                json={
                    "model": self.model,
                    "input": text,
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            embedding: list[float] = data["embeddings"][0]
            logger.info(
                "OllamaEmbeddingProvider.embed: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OllamaEmbeddingProvider.embed: Failed — %s",
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

        url = f"{self.base_url}/api/embed"

        try:
            response = requests.post(
                url,
                json={
                    "model": self.model,
                    "input": valid_texts,
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            embeddings_list: list[list[float]] = data["embeddings"]

            for resp_idx, emb in enumerate(embeddings_list):
                original_idx = valid_indices[resp_idx]
                results[original_idx] = emb

            logger.info(
                "OllamaEmbeddingProvider.embed_batch: Generated %d embeddings",
                len(valid_texts),
            )
        except Exception as e:
            logger.error(
                "OllamaEmbeddingProvider.embed_batch: Failed — %s",
                e,
            )
            raise EmbeddingBatchError(
                f"Ollama batch embedding failed: {e}",
                partial_results=results,
            ) from e

        return results

    def embed_query(self, text: str) -> list[float]:
        """Embed a query string.

        Raises:
            ValueError: If *text* is empty or whitespace-only.
            requests.exceptions.RequestException: If the API call fails.
        """
        if not text or not text.strip():
            raise ValueError("text must be non-empty")

        url = f"{self.base_url}/api/embed"

        try:
            response = requests.post(
                url,
                json={
                    "model": self.model,
                    "input": text,
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            embedding: list[float] = data["embeddings"][0]
            logger.info(
                "OllamaEmbeddingProvider.embed_query: Generated embedding "
                "(dimensions=%d)",
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error(
                "OllamaEmbeddingProvider.embed_query: Failed — %s",
                e,
            )
            raise
