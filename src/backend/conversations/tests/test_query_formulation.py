"""
Unit tests for the LLM Query Formulation module.

Tests cover:
- :func:`~conversations.query_formulation.formulate_query`
- :func:`~conversations.query_formulation._parse_formulation_response`
- :func:`~conversations.query_formulation._build_formulation_messages`

All external dependencies (``get_chat_provider``) are mocked using
``unittest.mock.patch``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from conversations.query_formulation import (
    FTS_QUERY_MAX_LENGTH,
    VECTOR_QUERY_MAX_LENGTH,
    QueryFormulationResult,
    _build_formulation_messages,
    _parse_formulation_response,
    formulate_query,
)


# ---------------------------------------------------------------------------
# BuildFormulationMessagesTests
# ---------------------------------------------------------------------------


class BuildFormulationMessagesTests:
    """Tests for :func:`~conversations.query_formulation._build_formulation_messages`."""

    def test_returns_system_and_user_messages(self) -> None:
        """Verify the messages array has system prompt and user query."""
        messages = _build_formulation_messages("test query")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test query"

    def test_system_prompt_contains_key_instructions(self) -> None:
        """System prompt includes Persian legal search instructions."""
        messages = _build_formulation_messages("test")
        system_content = messages[0]["content"]
        assert "Persian legal search query optimizer" in system_content
        assert "fts_query" in system_content
        assert "vector_query" in system_content
        assert "websearch" in system_content


# ---------------------------------------------------------------------------
# ParseFormulationResponseTests
# ---------------------------------------------------------------------------


class ParseFormulationResponseTests:
    """Tests for :func:`~conversations.query_formulation._parse_formulation_response`."""

    def test_valid_json(self) -> None:
        """Valid JSON with both fields returns correct dataclass."""
        raw = json.dumps({
            "fts_query": "ماده 22 قانون مدنی",
            "vector_query": "ماده 22 قانون مدنی",
        })
        result = _parse_formulation_response(raw)
        assert result.fts_query == "ماده 22 قانون مدنی"
        assert result.vector_query == "ماده 22 قانون مدنی"

    def test_valid_json_with_mixed_language(self) -> None:
        """Mixed-language query preserves English terms."""
        raw = json.dumps({
            "fts_query": "penalty کلاهبرداری Islamic Penal Code مجازات",
            "vector_query": "What is the penalty for کلاهبرداری under the Islamic Penal Code",
        })
        result = _parse_formulation_response(raw)
        assert "penalty" in result.fts_query
        assert "کلاهبرداری" in result.fts_query
        assert "Islamic Penal Code" in result.vector_query

    def test_invalid_json_returns_empty_fields(self) -> None:
        """Non-JSON response returns QueryFormulationResult with empty strings."""
        result = _parse_formulation_response("this is not json")
        assert result.fts_query == ""
        assert result.vector_query == ""

    def test_missing_fts_query_key(self) -> None:
        """JSON missing fts_query key returns empty fts_query."""
        raw = json.dumps({"vector_query": "some query"})
        result = _parse_formulation_response(raw)
        assert result.fts_query == ""
        assert result.vector_query == "some query"

    def test_missing_vector_query_key(self) -> None:
        """JSON missing vector_query key returns empty vector_query."""
        raw = json.dumps({"fts_query": "some keywords"})
        result = _parse_formulation_response(raw)
        assert result.fts_query == "some keywords"
        assert result.vector_query == ""

    def test_fts_query_exceeds_max_length(self) -> None:
        """fts_query longer than FTS_QUERY_MAX_LENGTH is truncated."""
        long_fts = "x" * (FTS_QUERY_MAX_LENGTH + 100)
        raw = json.dumps({
            "fts_query": long_fts,
            "vector_query": "short query",
        })
        result = _parse_formulation_response(raw)
        assert len(result.fts_query) == FTS_QUERY_MAX_LENGTH
        assert result.vector_query == "short query"

    def test_vector_query_exceeds_max_length(self) -> None:
        """vector_query longer than VECTOR_QUERY_MAX_LENGTH is truncated."""
        long_vector = "x" * (VECTOR_QUERY_MAX_LENGTH + 100)
        raw = json.dumps({
            "fts_query": "short keywords",
            "vector_query": long_vector,
        })
        result = _parse_formulation_response(raw)
        assert result.fts_query == "short keywords"
        assert len(result.vector_query) == VECTOR_QUERY_MAX_LENGTH

    def test_fts_query_is_not_string(self) -> None:
        """fts_query is a number, reset to empty string."""
        raw = json.dumps({"fts_query": 12345, "vector_query": "query"})
        result = _parse_formulation_response(raw)
        assert result.fts_query == ""
        assert result.vector_query == "query"

    def test_vector_query_is_not_string(self) -> None:
        """vector_query is a list, reset to empty string."""
        raw = json.dumps({"fts_query": "keywords", "vector_query": ["a", "b"]})
        result = _parse_formulation_response(raw)
        assert result.fts_query == "keywords"
        assert result.vector_query == ""

    def test_strips_markdown_code_fences(self) -> None:
        """Response wrapped in ```json ... ``` fences is parsed correctly."""
        raw = "```json\n{\"fts_query\": \"test\", \"vector_query\": \"test query\"}\n```"
        result = _parse_formulation_response(raw)
        assert result.fts_query == "test"
        assert result.vector_query == "test query"

    def test_empty_json_object(self) -> None:
        """Empty JSON object returns empty strings."""
        raw = json.dumps({})
        result = _parse_formulation_response(raw)
        assert result.fts_query == ""
        assert result.vector_query == ""


# ---------------------------------------------------------------------------
# FormulateQueryTests
# ---------------------------------------------------------------------------


class FormulateQueryTests:
    """Tests for :func:`~conversations.query_formulation.formulate_query`."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_success(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """Mock chat provider returns valid JSON; verify QueryFormulationResult fields."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({
                "fts_query": "ماده 22 قانون مدنی",
                "vector_query": "ماده 22 قانون مدنی",
            }),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query("ماده ۲۲ قانون مدنی رو برام توضیح بده")

        # Assert
        assert result.fts_query == "ماده 22 قانون مدنی"
        assert result.vector_query == "ماده 22 قانون مدنی"

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_mixed_language(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """Mixed-language query preserves English terms."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({
                "fts_query": "penalty کلاهبرداری Islamic Penal Code مجازات",
                "vector_query": "What is the penalty for کلاهبرداری under the Islamic Penal Code",
            }),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query(
            "What is the penalty for کلاهبرداری under Islamic Penal Code?"
        )

        # Assert
        assert "penalty" in result.fts_query
        assert "کلاهبرداری" in result.fts_query
        assert "Islamic Penal Code" in result.vector_query

    # ------------------------------------------------------------------
    # Fallback paths
    # ------------------------------------------------------------------

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_invalid_json_fallback(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """LLM returns non-JSON; verify fallback to raw query."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "this is not valid json",
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query("raw user query text")

        # Assert — falls back to raw query for both fields
        assert result.fts_query == "raw user query text"
        assert result.vector_query == "raw user query text"

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_missing_fields_fallback(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """LLM returns JSON missing fts_query; verify fallback for that field."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({"vector_query": "only vector query"}),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query("raw user query")

        # Assert — fts_query falls back, vector_query uses LLM result
        assert result.fts_query == "raw user query"
        assert result.vector_query == "only vector query"

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_empty_fields_fallback(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """LLM returns JSON with empty strings; verify fallback."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({"fts_query": "", "vector_query": ""}),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query("raw user query text")

        # Assert — both fields fall back to raw query
        assert result.fts_query == "raw user query text"
        assert result.vector_query == "raw user query text"

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_api_error_fallback(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """Chat provider raises exception; verify fallback to raw query."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = Exception("API connection error")
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = formulate_query("raw user query text")

        # Assert — falls back to raw query
        assert result.fts_query == "raw user query text"
        assert result.vector_query == "raw user query text"

    # ------------------------------------------------------------------
    # Short-circuit paths
    # ------------------------------------------------------------------

    def test_formulate_query_disabled(self) -> None:
        """QUERY_FORMULATION_ENABLED=False returns raw query without calling provider."""
        with override_settings(QUERY_FORMULATION_ENABLED=False):
            result = formulate_query("some longer query text here")

        assert result.fts_query == "some longer query text here"
        assert result.vector_query == "some longer query text here"

    def test_formulate_query_short_query(self) -> None:
        """Query shorter than 10 chars returns raw query without calling provider."""
        result = formulate_query("short")

        assert result.fts_query == "short"
        assert result.vector_query == "short"

    # ------------------------------------------------------------------
    # Provider call verification
    # ------------------------------------------------------------------

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_calls_provider_with_correct_args(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """Verify the chat provider is called with the right messages and max_tokens."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({
                "fts_query": "test keywords",
                "vector_query": "test query",
            }),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        formulate_query("test user question here")

        # Assert
        mock_provider.chat.assert_called_once()
        call_args = mock_provider.chat.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test user question here"
        assert call_args.kwargs["max_tokens"] == 150

    @patch("conversations.query_formulation.get_chat_provider")
    def test_formulate_query_uses_configured_max_tokens(
        self,
        mock_get_chat_provider: MagicMock,
    ) -> None:
        """Custom QUERY_FORMULATION_MAX_TOKENS is passed to the provider."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": json.dumps({
                "fts_query": "test",
                "vector_query": "test query",
            }),
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        with override_settings(QUERY_FORMULATION_MAX_TOKENS=300):
            formulate_query("test user question here")

        # Assert
        mock_provider.chat.assert_called_once()
        call_args = mock_provider.chat.call_args
        assert call_args.kwargs["max_tokens"] == 300
