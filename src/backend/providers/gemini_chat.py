"""Gemini chat provider — wraps Google Gemini generateContent API."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings

from providers.base import BaseChatProvider, RateLimitError

logger = logging.getLogger(__name__)


class GeminiChatProvider(BaseChatProvider):
    """Uses Google Gemini API for chat completions.

    Converts OpenAI-style messages to Gemini's ``generateContent`` format
    and returns a standardized response dict.
    """

    def __init__(self) -> None:
        self.api_key: str = settings.GOOGLE_API_KEY
        self.model: str = settings.GEMINI_CHAT_MODEL
        self.base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request via Gemini's generateContent API.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
                       Supported roles: ``system``, ``user``, ``assistant``.
            max_tokens: Override the default max output tokens.
            model: Override the default model.

        Returns:
            A dict with:
            - ``content`` (str): The assistant's response text.
            - ``token_usage`` (dict): ``prompt_tokens``, ``completion_tokens``,
              ``total_tokens``.
        """
        model_name = model or self.model
        url = (
            f"{self.base_url}/models/{model_name}:generateContent"
            f"?key={self.api_key}"
        )

        # Convert OpenAI-style messages to Gemini format
        system_instruction = None
        contents: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # Gemini uses a separate system_instruction field
                system_instruction = {"parts": [{"text": content}]}
            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}],
                })
            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}],
                })

        # Build the request payload
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction

        generation_config: dict[str, Any] = {}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if generation_config:
            payload["generationConfig"] = generation_config

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as e:
            logger.exception("GeminiChatProvider.chat: API call failed")
            if response.status_code == 429:
                raise RateLimitError(str(e)) from e
            raise
        except Exception as e:
            logger.exception("GeminiChatProvider.chat: API call failed")
            raise

        # Parse the response
        content = ""
        try:
            candidate = data["candidates"][0]
            content = candidate["content"]["parts"][0].get("text", "")
        except (KeyError, IndexError) as e:
            logger.warning(
                "GeminiChatProvider.chat: Could not parse response content — %s",
                e,
            )

        # Extract token usage if available
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        try:
            usage_metadata = data.get("usageMetadata", {})
            if usage_metadata:
                token_usage = {
                    "prompt_tokens": usage_metadata.get(
                        "promptTokenCount", 0
                    ),
                    "completion_tokens": usage_metadata.get(
                        "candidatesTokenCount", 0
                    ),
                    "total_tokens": usage_metadata.get("totalTokenCount", 0),
                }
        except Exception as e:
            logger.warning(
                "GeminiChatProvider.chat: Could not parse token usage — %s",
                e,
            )

        logger.info(
            "GeminiChatProvider.chat: Completed (model=%s, total_tokens=%d)",
            model_name,
            token_usage["total_tokens"],
        )

        return {
            "content": content,
            "token_usage": token_usage,
        }
