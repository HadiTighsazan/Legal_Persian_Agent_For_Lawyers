"""Gemini embedding provider — wraps Google Gemini Embedding API."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings

from providers.base import BaseEmbeddingProvider, EmbeddingBatchError, EMBEDDING_SUB_BATCH_SIZE as SUB_BATCH_SIZE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES: int = 2
"""Number of retry attempts for failed API calls."""

_TIMEOUT_SECONDS: int = 30
"""HTTP request timeout for Gemini API calls."""


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Uses Google Gemini Embedding API (``gemini-embedding-001``, etc.)."""

    def __init__(self) -> None:
        self.api_key: str = settings.GOOGLE_API_KEY
        self.base_url: str = "https://generativelanguage.googleapis.com/v1beta"
        self.model: str = settings.GEMINI_EMBEDDING_MODEL
        self._dimensions: int = 768
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dimensions(self) -> int:
        return self._dimensions

    # ------------------------------------------------------------------
    # Connection pool
    # ------------------------------------------------------------------

    @property
    def session(self) -> requests.Session:
        """Lazily-initialized ``requests.Session`` with connection pooling.

        Uses ``HTTPAdapter`` with ``pool_connections=10`` and
        ``pool_maxsize=20`` to reuse TCP connections across API calls,
        avoiding the overhead of TCP handshake + TLS negotiation per
        request.
        """
        if self._session is None:
            self._session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10,
                pool_maxsize=20,
            )
            self._session.mount("https://", adapter)
        return self._session

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

        url = f"{self.base_url}/models/{self.model}:embedContent?key={self.api_key}"

        for attempt in range(_MAX_RETRIES):
            try:
                response = self.session.post(
                    url,
                    json={
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": text}]},
                        "outputDimensionality": self._dimensions,
                    },
                    timeout=_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                embedding: list[float] = data["embedding"]["values"]
                logger.info(
                    "GeminiEmbeddingProvider.embed: Generated embedding (dimensions=%d)",
                    len(embedding),
                )
                return embedding

            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time: float = 2.0**attempt
                    logger.warning(
                        "GeminiEmbeddingProvider.embed: Timeout, retrying in %.0fs "
                        "(attempt %d/%d)",
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "GeminiEmbeddingProvider.embed: Timeout after %d retries",
                        _MAX_RETRIES,
                    )
                    return None

            except requests.exceptions.RequestException as e:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0**attempt
                    logger.warning(
                        "GeminiEmbeddingProvider.embed: Request failed (%s), "
                        "retrying in %.0fs (attempt %d/%d)",
                        e,
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "GeminiEmbeddingProvider.embed: Request failed after "
                        "%d retries — %s",
                        _MAX_RETRIES,
                        e,
                    )
                    return None

        return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of texts, handling sub-batching.

        Results are returned in the same order as the input list.  Items that
        fail (empty text, API error) get ``None`` at the corresponding position.
        """
        results: list[list[float] | None] = [None] * len(texts)

        url = (
            f"{self.base_url}/models/{self.model}:batchEmbedContents"
            f"?key={self.api_key}"
        )

        for batch_start in range(0, len(texts), SUB_BATCH_SIZE):
            batch_end = min(batch_start + SUB_BATCH_SIZE, len(texts))
            sub_batch = texts[batch_start:batch_end]

            # Pre-fill None for empty texts in this sub-batch.
            valid_indices: list[int] = []
            valid_texts: list[str] = []
            for i, t in enumerate(sub_batch):
                idx = batch_start + i
                if not t or not t.strip():
                    logger.info(
                        "GeminiEmbeddingProvider.embed_batch: Item %d failed — empty text",
                        idx,
                    )
                    results[idx] = None
                else:
                    valid_indices.append(idx)
                    valid_texts.append(t)

            if not valid_texts:
                continue

            # Build Gemini batch request payload
            requests_payload = []
            for t in valid_texts:
                requests_payload.append({
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self._dimensions,
                })

            # Send the sub-batch to Gemini with retry logic.
            for attempt in range(_MAX_RETRIES):
                try:
                    response = self.session.post(
                        url,
                        json={"requests": requests_payload},
                        timeout=_TIMEOUT_SECONDS,
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings_data: list[dict] = data["embeddings"]

                    # Map results back by index within the sub-batch.
                    for resp_idx, emb_data in enumerate(embeddings_data):
                        original_idx = valid_indices[resp_idx]
                        results[original_idx] = emb_data["values"]

                    logger.info(
                        "GeminiEmbeddingProvider.embed_batch: Sub-batch %d–%d complete "
                        "(embeddings=%d)",
                        batch_start,
                        batch_end,
                        len(embeddings_data),
                    )
                    break  # Success — exit retry loop.

                except requests.exceptions.Timeout:
                    if attempt < _MAX_RETRIES - 1:
                        sleep_time = 2.0**attempt
                        logger.warning(
                            "GeminiEmbeddingProvider.embed_batch: Timeout, "
                            "retrying in %.0fs (attempt %d/%d)",
                            sleep_time,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(
                            "GeminiEmbeddingProvider.embed_batch: Timeout after "
                            "%d retries for sub-batch %d–%d",
                            _MAX_RETRIES,
                            batch_start,
                            batch_end,
                        )
                        raise EmbeddingBatchError(
                            f"Gemini batch embedding timed out after {_MAX_RETRIES} retries "
                            f"for sub-batch {batch_start}–{batch_end}",
                            partial_results=results,
                        )

                except requests.exceptions.RequestException as e:
                    if attempt < _MAX_RETRIES - 1:
                        sleep_time = 2.0**attempt
                        logger.warning(
                            "GeminiEmbeddingProvider.embed_batch: Request failed "
                            "(%s), retrying in %.0fs (attempt %d/%d)",
                            e,
                            sleep_time,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(
                            "GeminiEmbeddingProvider.embed_batch: Request failed "
                            "after %d retries for sub-batch %d–%d — %s",
                            _MAX_RETRIES,
                            batch_start,
                            batch_end,
                            e,
                        )
                        raise EmbeddingBatchError(
                            f"Gemini batch embedding failed after {_MAX_RETRIES} retries "
                            f"for sub-batch {batch_start}–{batch_end}: {e}",
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

        url = f"{self.base_url}/models/{self.model}:embedContent?key={self.api_key}"

        for attempt in range(_MAX_RETRIES):
            try:
                response = self.session.post(
                    url,
                    json={
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": text}]},
                        "outputDimensionality": self._dimensions,
                    },
                    timeout=_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                embedding: list[float] = data["embedding"]["values"]
                logger.info(
                    "GeminiEmbeddingProvider.embed_query: Generated embedding "
                    "(dimensions=%d)",
                    len(embedding),
                )
                return embedding

            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0**attempt
                    logger.warning(
                        "GeminiEmbeddingProvider.embed_query: Timeout, retrying "
                        "in %.0fs (attempt %d/%d)",
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "GeminiEmbeddingProvider.embed_query: Timeout after "
                        "%d retries",
                        _MAX_RETRIES,
                    )
                    raise

            except requests.exceptions.RequestException:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0**attempt
                    logger.warning(
                        "GeminiEmbeddingProvider.embed_query: Request failed, "
                        "retrying in %.0fs (attempt %d/%d)",
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "GeminiEmbeddingProvider.embed_query: Request failed "
                        "after %d retries",
                        _MAX_RETRIES,
                    )
                    raise

        raise RuntimeError("Unexpected error in GeminiEmbeddingProvider.embed_query")
