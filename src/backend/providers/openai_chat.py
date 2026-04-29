"""OpenAI chat provider — wraps OpenAI Chat Completions API."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from providers.base import BaseChatProvider

logger = logging.getLogger(__name__)


class OpenAIChatProvider(BaseChatProvider):
    """Uses OpenAI's Chat Completions API (``gpt-4o-mini``, etc.)."""

    def __init__(self) -> None:
        import openai

        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model: str = settings.OPENAI_CHAT_MODEL
        self.max_tokens: int = settings.OPENAI_CHAT_MAX_TOKENS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            max_tokens: Override the default max tokens for this call.
            model: Override the default model for this call.

        Returns:
            A dict with:
            - ``content`` (str): The assistant's response text.
            - ``token_usage`` (dict): ``prompt_tokens``, ``completion_tokens``,
              ``total_tokens``.
        """
        try:
            response = self.client.chat.completions.create(
                model=model or self.model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens or self.max_tokens,
            )
        except Exception as e:
            logger.exception("OpenAIChatProvider.chat: API call failed")
            raise

        choice = response.choices[0]
        response_content = choice.message.content or ""

        token_usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens
            if response.usage
            else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }

        logger.info(
            "OpenAIChatProvider.chat: Completed (model=%s, total_tokens=%d)",
            model or self.model,
            token_usage["total_tokens"],
        )

        return {
            "content": response_content,
            "token_usage": token_usage,
        }
