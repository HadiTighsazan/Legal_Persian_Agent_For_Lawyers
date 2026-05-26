"""
Unit tests for the Question Router module (Phase 2a — Global RAG).

Tests cover:
- :func:`~conversations.question_router.route_question`
- :func:`~conversations.question_router._build_router_messages`
- :func:`~conversations.question_router._parse_router_response`
- :func:`~conversations.question_router._all_hubs_fallback`

All external dependencies (``get_chat_provider``) are mocked using
``unittest.mock.patch``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from conversations.question_router import (
    ALL_HUBS,
    SUB_QUERY_MAX_LENGTH,
    HUB_LABELS,
    RouterResult,
    SubQuery,
    _all_hubs_fallback,
    _build_router_messages,
    _parse_router_response,
    route_question,
)


# ---------------------------------------------------------------------------
# BuildRouterMessagesTests
# ---------------------------------------------------------------------------


class BuildRouterMessagesTests:
    """Tests for :func:`~conversations.question_router._build_router_messages`."""

    def test_returns_system_and_user_messages(self) -> None:
        """Verify the messages array has system prompt and user query."""
        messages = _build_router_messages("test query")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test query"

    def test_system_prompt_contains_hub_labels(self) -> None:
        """System prompt includes all three hub labels."""
        messages = _build_router_messages("test")
        system_content = messages[0]["content"]
        for label in HUB_LABELS.values():
            assert label in system_content
        assert "legislation" in system_content
        assert "judicial_precedent" in system_content
        assert "advisory_opinion" in system_content

    def test_system_prompt_contains_json_format_instructions(self) -> None:
        """System prompt includes JSON output format instructions."""
        messages = _build_router_messages("test")
        system_content = messages[0]["content"]
        assert "fts_query" in system_content
        assert "vector_query" in system_content
        assert "sub_queries" in system_content
        assert "reasoning" in system_content
        assert "hypothetical_answer" in system_content


# ---------------------------------------------------------------------------
# ParseRouterResponseTests
# ---------------------------------------------------------------------------


class ParseRouterResponseTests:
    """Tests for :func:`~conversations.question_router._parse_router_response`."""

    def test_valid_json_all_hubs(self) -> None:
        """Valid JSON with all three hubs returns correct RouterResult."""
        raw = json.dumps({
            "reasoning": "All hubs are relevant to this legal question.",
            "hypothetical_answer": "بر اساس قانون مجازات اسلامی، مجازات کلاهبرداری حبس است.",
            "sub_queries": {
                "legislation": {
                    "fts_query": "مجازات کلاهبرداری قانون مجازات اسلامی",
                    "vector_query": "مجازات کلاهبرداری حسب قانون مجازات اسلامی حبس است.",
                },
                "judicial_precedent": {
                    "fts_query": "کلاهبرداری رأی دیوان عالی کشور",
                    "vector_query": "در رویه قضایی مجازات کلاهبرداری تعیین می‌گردد.",
                },
                "advisory_opinion": {
                    "fts_query": "کلاهبرداری نظریه مشورتی",
                    "vector_query": "نظریه مشورتی در خصوص مجازات کلاهبرداری.",
                },
            },
        })
        result = _parse_router_response(raw)
        assert result.reasoning == "All hubs are relevant to this legal question."
        assert result.hypothetical_answer == "بر اساس قانون مجازات اسلامی، مجازات کلاهبرداری حبس است."
        assert len(result.sub_queries) == 3
        assert "legislation" in result.sub_queries
        assert "judicial_precedent" in result.sub_queries
        assert "advisory_opinion" in result.sub_queries
        assert result.sub_queries["legislation"].fts_query == "مجازات کلاهبرداری قانون مجازات اسلامی"
        assert result.sub_queries["judicial_precedent"].fts_query == "کلاهبرداری رأی دیوان عالی کشور"
        assert result.sub_queries["advisory_opinion"].fts_query == "کلاهبرداری نظریه مشورتی"

    def test_valid_json_some_hubs_empty(self) -> None:
        """Valid JSON with some hubs having empty queries."""
        raw = json.dumps({
            "reasoning": "Only legislation is relevant.",
            "hypothetical_answer": "ماده 22 قانون مدنی مربوط به تصرف مال غیر است.",
            "sub_queries": {
                "legislation": {
                    "fts_query": "ماده 22 قانون مدنی",
                    "vector_query": "ماده 22 قانون مدنی: هر کس مال غیر را تصرف کند.",
                },
                "judicial_precedent": {
                    "fts_query": "",
                    "vector_query": "",
                },
                "advisory_opinion": {
                    "fts_query": "",
                    "vector_query": "",
                },
            },
        })
        result = _parse_router_response(raw)
        assert result.reasoning == "Only legislation is relevant."
        assert result.hypothetical_answer == "ماده 22 قانون مدنی مربوط به تصرف مال غیر است."
        assert result.sub_queries["legislation"].fts_query == "ماده 22 قانون مدنی"
        assert result.sub_queries["judicial_precedent"].fts_query == ""
        assert result.sub_queries["advisory_opinion"].fts_query == ""

    def test_invalid_json_returns_empty_result(self) -> None:
        """Non-JSON response returns RouterResult with empty sub_queries."""
        result = _parse_router_response("this is not json")
        assert result.reasoning == ""
        assert len(result.sub_queries) == 0

    def test_json_with_markdown_code_fence(self) -> None:
        """JSON wrapped in ```json ... ``` code fence is parsed correctly."""
        raw = """```json
{
  "reasoning": "Test reasoning.",
  "hypothetical_answer": "A hypothetical legal answer for testing.",
  "sub_queries": {
    "legislation": {
      "fts_query": "test query",
      "vector_query": "test vector"
    },
    "judicial_precedent": {
      "fts_query": "",
      "vector_query": ""
    },
    "advisory_opinion": {
      "fts_query": "",
      "vector_query": ""
    }
  }
}
```"""
        result = _parse_router_response(raw)
        assert result.reasoning == "Test reasoning."
        assert result.hypothetical_answer == "A hypothetical legal answer for testing."
        assert result.sub_queries["legislation"].fts_query == "test query"

    def test_missing_sub_queries_key(self) -> None:
        """JSON missing sub_queries key returns empty sub_queries."""
        raw = json.dumps({
            "reasoning": "No sub-queries.",
            "hypothetical_answer": "Some answer.",
        })
        result = _parse_router_response(raw)
        assert result.reasoning == "No sub-queries."
        assert result.hypothetical_answer == "Some answer."
        assert len(result.sub_queries) == 0

    def test_missing_reasoning_key(self) -> None:
        """JSON missing reasoning key returns empty reasoning string."""
        raw = json.dumps({
            "hypothetical_answer": "Some answer.",
            "sub_queries": {
                "legislation": {"fts_query": "test", "vector_query": "test"},
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {"fts_query": "", "vector_query": ""},
            },
        })
        result = _parse_router_response(raw)
        assert result.reasoning == ""
        assert result.hypothetical_answer == "Some answer."

    def test_truncates_long_queries(self) -> None:
        """Queries exceeding SUB_QUERY_MAX_LENGTH are truncated."""
        long_fts = "a" * (SUB_QUERY_MAX_LENGTH + 100)
        long_vector = "b" * (SUB_QUERY_MAX_LENGTH + 100)
        long_hypo = "c" * (SUB_QUERY_MAX_LENGTH + 100)
        raw = json.dumps({
            "reasoning": "Long queries.",
            "hypothetical_answer": long_hypo,
            "sub_queries": {
                "legislation": {
                    "fts_query": long_fts,
                    "vector_query": long_vector,
                },
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {"fts_query": "", "vector_query": ""},
            },
        })
        result = _parse_router_response(raw)
        assert len(result.sub_queries["legislation"].fts_query) == SUB_QUERY_MAX_LENGTH
        assert len(result.sub_queries["legislation"].vector_query) == SUB_QUERY_MAX_LENGTH
        assert len(result.hypothetical_answer) == SUB_QUERY_MAX_LENGTH
        assert result.hypothetical_answer == "c" * SUB_QUERY_MAX_LENGTH

    def test_non_dict_sub_queries_returns_empty(self) -> None:
        """sub_queries that is not a dict returns empty sub_queries."""
        raw = json.dumps({
            "reasoning": "test",
            "hypothetical_answer": "answer",
            "sub_queries": "not a dict",
        })
        result = _parse_router_response(raw)
        assert result.hypothetical_answer == "answer"
        assert len(result.sub_queries) == 0

    def test_non_dict_hub_data_skips_hub(self) -> None:
        """Hub data that is not a dict is skipped."""
        raw = json.dumps({
            "reasoning": "test",
            "hypothetical_answer": "answer",
            "sub_queries": {
                "legislation": "not a dict",
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {"fts_query": "", "vector_query": ""},
            },
        })
        result = _parse_router_response(raw)
        assert result.hypothetical_answer == "answer"
        assert "legislation" not in result.sub_queries

    def test_non_string_fields_default_to_empty(self) -> None:
        """Non-string fts_query/vector_query default to empty string."""
        raw = json.dumps({
            "reasoning": "test",
            "hypothetical_answer": 12345,
            "sub_queries": {
                "legislation": {
                    "fts_query": 123,
                    "vector_query": ["not", "a", "string"],
                },
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {"fts_query": "", "vector_query": ""},
            },
        })
        result = _parse_router_response(raw)
        assert result.sub_queries["legislation"].fts_query == ""
        assert result.sub_queries["legislation"].vector_query == ""
        assert result.hypothetical_answer == ""


# ---------------------------------------------------------------------------
# AllHubsFallbackTests
# ---------------------------------------------------------------------------


class AllHubsFallbackTests:
    """Tests for :func:`~conversations.question_router._all_hubs_fallback`."""

    def test_returns_all_hubs_with_raw_query(self) -> None:
        """Fallback returns all hubs with the raw user query."""
        result = _all_hubs_fallback("raw user query", "LLM failed")
        assert len(result.sub_queries) == 3
        for hub in ALL_HUBS:
            assert hub in result.sub_queries
            assert result.sub_queries[hub].fts_query == "raw user query"
            assert result.sub_queries[hub].vector_query == "raw user query"
        assert result.reasoning == "LLM failed"
        assert result.hypothetical_answer == "raw user query"

    def test_reasoning_reflects_failure_reason(self) -> None:
        """Reasoning string contains the provided failure reason."""
        result = _all_hubs_fallback("query", "Network error")
        assert "Network error" in result.reasoning
        assert result.hypothetical_answer == "query"


# ---------------------------------------------------------------------------
# RouteQuestionTests
# ---------------------------------------------------------------------------


class RouteQuestionTests:
    """Tests for :func:`~conversations.question_router.route_question`."""

    _VALID_LLM_RESPONSE: str = json.dumps({
        "reasoning": "Legislation and judicial precedent are relevant.",
        "hypothetical_answer": "بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است.",
        "sub_queries": {
            "legislation": {
                "fts_query": "مجازات جعل اسناد رسمی",
                "vector_query": "مجازات جعل اسناد رسمی حسب قانون مجازات اسلامی حبس است.",
            },
            "judicial_precedent": {
                "fts_query": "جعل اسناد رسمی رأی وحدت رویه",
                "vector_query": "در رویه قضایی مجازات جعل اسناد رسمی تعیین می‌گردد.",
            },
            "advisory_opinion": {
                "fts_query": "",
                "vector_query": "",
            },
        },
    })

    @patch("conversations.question_router.get_chat_provider")
    def test_returns_router_result_on_success(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Successful LLM call returns a RouterResult with parsed sub-queries."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        result = route_question("مجازات جعل اسناد رسمی چیست؟")

        assert isinstance(result, RouterResult)
        assert "legislation" in result.sub_queries
        assert "judicial_precedent" in result.sub_queries
        assert result.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"
        assert result.sub_queries["judicial_precedent"].fts_query == "جعل اسناد رسمی رأی وحدت رویه"
        assert result.sub_queries["advisory_opinion"].fts_query == ""
        assert "Legislation and judicial precedent" in result.reasoning
        assert result.hypothetical_answer == "بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است."

    @patch("conversations.question_router.get_chat_provider")
    def test_passes_user_query_to_llm(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """The user query is passed to the LLM as the user message."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        route_question("What is the penalty for fraud?")

        call_args = mock_provider.chat.call_args[1]
        messages = call_args["messages"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "What is the penalty for fraud?"

    @patch("conversations.question_router.get_chat_provider")
    def test_fallback_on_llm_exception(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When LLM raises an exception, fallback queries all hubs."""
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = ConnectionError("API unreachable")
        mock_get_provider.return_value = mock_provider

        result = route_question("test query")

        # Should fallback to all hubs with raw query
        for hub in ALL_HUBS:
            assert result.sub_queries[hub].fts_query == "test query"
            assert result.sub_queries[hub].vector_query == "test query"
        assert "API unreachable" in result.reasoning
        assert result.hypothetical_answer == "test query"

    @patch("conversations.question_router.get_chat_provider")
    def test_fallback_on_invalid_json(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When LLM returns invalid JSON, fallback queries all hubs."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": "not valid json"}
        mock_get_provider.return_value = mock_provider

        result = route_question("test query")

        for hub in ALL_HUBS:
            assert result.sub_queries[hub].fts_query == "test query"
        assert result.hypothetical_answer == "test query"

    @override_settings(QUERY_FORMULATION_ENABLED=False)
    @patch("conversations.question_router.get_chat_provider")
    def test_short_circuit_when_disabled(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When QUERY_FORMULATION_ENABLED is False, skip LLM call."""
        result = route_question("test query")

        # LLM should NOT be called
        mock_get_provider.assert_not_called()

        # All hubs should have raw query
        for hub in ALL_HUBS:
            assert result.sub_queries[hub].fts_query == "test query"
            assert result.sub_queries[hub].vector_query == "test query"
        assert "Question routing disabled" in result.reasoning
        assert result.hypothetical_answer == "test query"

    @patch("conversations.question_router.get_chat_provider")
    def test_missing_hub_in_response_adds_fallback(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When LLM response is missing a hub, it's added with raw query fallback."""
        incomplete_response = json.dumps({
            "reasoning": "Only legislation is relevant.",
            "hypothetical_answer": "بر اساس قانون، مجازات حبس است.",
            "sub_queries": {
                "legislation": {
                    "fts_query": "test fts",
                    "vector_query": "test vector",
                },
            },
        })
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": incomplete_response}
        mock_get_provider.return_value = mock_provider

        result = route_question("test query")

        # Missing hubs should be added with raw query fallback
        assert "legislation" in result.sub_queries
        assert "judicial_precedent" in result.sub_queries
        assert "advisory_opinion" in result.sub_queries
        assert result.sub_queries["judicial_precedent"].fts_query == "test query"
        assert result.sub_queries["advisory_opinion"].fts_query == "test query"
        assert result.hypothetical_answer == "بر اساس قانون، مجازات حبس است."

    @patch("conversations.question_router.get_chat_provider")
    def test_empty_fts_query_falls_back_to_raw(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When fts_query is whitespace-only, fallback to raw query."""
        response = json.dumps({
            "reasoning": "test",
            "hypothetical_answer": "بر اساس قانون مجازات اسلامی، مجازات حبس است.",
            "sub_queries": {
                "legislation": {
                    "fts_query": "   ",
                    "vector_query": "valid vector query",
                },
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {"fts_query": "", "vector_query": ""},
            },
        })
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": response}
        mock_get_provider.return_value = mock_provider

        result = route_question("raw fallback query")

        # fts_query was whitespace-only, should fallback to raw
        assert result.sub_queries["legislation"].fts_query == "raw fallback query"
        # vector_query was valid, should be preserved
        assert result.sub_queries["legislation"].vector_query == "valid vector query"
        assert result.hypothetical_answer == "بر اساس قانون مجازات اسلامی، مجازات حبس است."
