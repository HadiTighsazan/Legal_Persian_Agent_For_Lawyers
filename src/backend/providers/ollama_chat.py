"""Ollama chat provider — wraps Ollama's /api/chat endpoint."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

from providers.base import BaseChatProvider, RateLimitError

logger = logging.getLogger(__name__)


class OllamaChatProvider(BaseChatProvider):
    """Uses Ollama's ``/api/chat`` endpoint for chat completions."""

    def __init__(self) -> None:
        self.base_url: str = settings.OLLAMA_BASE_URL
        self.model: str = settings.OLLAMA_CHAT_MODEL

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request via Ollama's /api/chat.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
                       Supported roles: ``system``, ``user``, ``assistant``.
            max_tokens: Override the default max output tokens (``options.num_predict``).
            model: Override the default model.

        Returns:
            A dict with:
            - ``content`` (str): The assistant's response text.
            - ``token_usage`` (dict): ``prompt_tokens``, ``completion_tokens``,
              ``total_tokens``.
        """
        model_name = model or self.model
        url = f"{self.base_url}/api/chat"

        # Build the request payload
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
        }

        if max_tokens is not None:
            payload.setdefault("options", {})["num_predict"] = max_tokens

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as e:
            logger.exception("OllamaChatProvider.chat: API call failed")
            if response.status_code == 429:
                raise RateLimitError(str(e)) from e
            raise
        except Exception as e:
            logger.exception("OllamaChatProvider.chat: API call failed")
            raise

        # Parse the response
        content = data.get("message", {}).get("content", "")

        # Extract token usage if available
        token_usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0)
            + data.get("eval_count", 0),
        }

        logger.info(
            "OllamaChatProvider.chat: Completed (model=%s, total_tokens=%d)",
            model_name,
            token_usage["total_tokens"],
        )

        return {
            "content": content,
            "token_usage": token_usage,
        }
