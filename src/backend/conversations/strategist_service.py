"""
Strategist Service — Interactive Case Analysis Pipeline.

Provides the :class:`StrategistService` class that orchestrates the guided
interview → research → analysis flow for the Interactive Strategist mode.

Phase 3 stub: ``process_message()`` returns a mock streaming response.
Real LLM logic will be added in a later iteration.
"""

from __future__ import annotations

import logging
from typing import Generator

logger = logging.getLogger(__name__)


class StrategistService:
    """Orchestrator for the Interactive Strategist pipeline.

    This service manages the guided interview flow where the LLM drives
    the conversation to gather case facts, then produces a structured
    strategic analysis with success probability, risks, and recommendations.

    .. note::

       Currently a stub. The ``process_message()`` method yields a mock
       streaming response. Real LLM integration will be added in a later
       phase.
    """

    def process_message(
        self,
        message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> Generator[tuple[str, dict], None, None]:
        """Process a user message in strategist mode.

        For now, yields a mock streaming response. In the future, this will
        run the full strategist pipeline: fact extraction → completeness
        checking → strategic analysis → report generation.

        Args:
            message: The user's message text.
            conversation_history: Optional list of prior message dicts with
                ``role`` and ``content`` keys.

        Yields:
            ``(event_type, data)`` tuples matching the same SSE protocol
            used by the RAG streaming endpoints:

            - ``("token", {"content": str})`` — A content token.
            - ``("done", {"content": str, "sources": list, "token_usage": dict})``
              — Streaming complete.
        """
        logger.info(
            "StrategistService.process_message: Processing message "
            "(stub mode, %d chars)",
            len(message),
        )

        mock_response = "This is a mock strategist response."

        # Yield the response token-by-token (word-level for mock)
        for word in mock_response.split(" "):
            yield ("token", {"content": word + " "})

        # Yield done event
        yield (
            "done",
            {
                "content": mock_response,
                "sources": [],
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )


# Module-level singleton for convenience
strategist_service = StrategistService()
