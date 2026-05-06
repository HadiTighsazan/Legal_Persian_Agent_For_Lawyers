"""OpenAI chat provider — wraps OpenAI Chat Completions API."""

from __future__ import annotations

import logging
from typing import Any, Generator

from django.conf import settings

from providers.base import BaseChatProvider, RateLimitError

logger = logging.getLogger(__name__)


class OpenAIChatProvider(BaseChatProvider):
    """OpenAI-compatible chat provider (works with OpenAI, DeepSeek, etc.).

    Reads ``CHAT_API_KEY`` and ``CHAT_BASE_URL`` from settings so it can
    target any OpenAI-compatible API (OpenAI, DeepSeek, Together, etc.).
    """

    def __init__(self) -> None:
        import openai
        from httpx import Client, Timeout

        # Configure HTTP client with timeouts to prevent hanging on
        # DNS resolution failures or unresponsive APIs. The default
        # OpenAI client has no connect timeout, which can cause
        # worker processes to hang indefinitely (e.g., when Docker
        # DNS cannot resolve the API hostname).
        http_client = Client(
            timeout=Timeout(
                connect=10.0,   # Max seconds to wait for connection
                read=30.0,      # Max seconds to wait for response
                write=30.0,     # Max seconds to send request
                pool=10.0,      # Max seconds to wait for connection pool
            ),
        )

        self.client = openai.OpenAI(
            api_key=settings.CHAT_API_KEY,
            base_url=settings.CHAT_BASE_URL,
            http_client=http_client,
        )
        self.model: str = settings.OPENAI_CHAT_MODEL
        self.max_tokens: int = settings.CHAT_MAX_TOKENS

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
            # Re-raise rate-limit errors as RateLimitError
            if "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(str(e)) from e
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

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> Generator[tuple[str, bool, dict | None], None, None]:
        """Stream a chat completion response token by token.

        Uses OpenAI's ``stream=True`` option to yield tokens as they arrive.

        Yields:
            ``(token_text, is_last, metadata)`` tuples.
            - ``token_text``: The next token string.
            - ``is_last``: ``True`` only for the final yield.
            - ``metadata``: ``None`` for intermediate tokens; on the final
              yield, contains ``{"token_usage": {...}}``.
        """
        try:
            stream = self.client.chat.completions.create(
                model=model or self.model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as e:
            logger.exception("OpenAIChatProvider.chat_stream: API call failed")
            if "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(str(e)) from e
            raise

        full_content: list[str] = []
        final_token_usage: dict[str, int] | None = None

        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    token = delta.content
                    full_content.append(token)
                    yield token, False, None

            # Capture token usage from the final chunk (stream_options={"include_usage": True})
            if chunk.usage:
                final_token_usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }

        # Final yield with token usage
        metadata = {"token_usage": final_token_usage} if final_token_usage else None
        yield "", True, metadata

        logger.info(
            "OpenAIChatProvider.chat_stream: Completed (model=%s, total_tokens=%d)",
            model or self.model,
            (final_token_usage or {}).get("total_tokens", 0),
        )
