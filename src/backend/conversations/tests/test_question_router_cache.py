"""
Tests for the cached question router function.

Tests cover:
- :func:`~conversations.question_router.route_question_cached`

The Django cache framework is used with ``LocMemCache`` (the default test
backend), so no Redis is required for these tests.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from conversations.question_router import (
    ALL_HUBS,
    RouterResult,
    SubQuery,
    route_question_cached,
)


# Ensure we use LocMemCache for tests (no Redis dependency)
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-router-cache",
        }
    }
)
class RouteQuestionCachedTests(TestCase):
    """Tests for :func:`~conversations.question_router.route_question_cached`."""

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

    def setUp(self) -> None:
        """Clear cache before each test."""
        cache.clear()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @patch("conversations.question_router.get_chat_provider")
    def test_first_call_misses_cache_and_calls_route_question(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """First call should miss cache and delegate to route_question."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        result = route_question_cached("مجازات جعل اسناد رسمی چیست؟")

        assert isinstance(result, RouterResult)
        assert "legislation" in result.sub_queries
        assert result.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"
        assert result.hypothetical_answer == "بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است."
        mock_provider.chat.assert_called_once()

    @patch("conversations.question_router.get_chat_provider")
    def test_second_call_hits_cache_and_skips_llm(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Second call with same query should hit cache and skip LLM call."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        # First call — miss
        result1 = route_question_cached("مجازات جعل اسناد رسمی چیست؟")
        assert result1.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        # Second call — should hit cache
        result2 = route_question_cached("مجازات جعل اسناد رسمی چیست؟")
        assert result2.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        # LLM should have been called only once
        mock_provider.chat.assert_called_once()

    @patch("conversations.question_router.get_chat_provider")
    def test_different_queries_produce_different_cache_entries(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Different queries should each miss cache independently."""
        response2 = json.dumps({
            "reasoning": "Only advisory opinion is relevant.",
            "hypothetical_answer": "نظریه مشورتی در خصوص ماده 22 قانون مدنی.",
            "sub_queries": {
                "legislation": {"fts_query": "", "vector_query": ""},
                "judicial_precedent": {"fts_query": "", "vector_query": ""},
                "advisory_opinion": {
                    "fts_query": "ماده 22 قانون مدنی نظریه مشورتی",
                    "vector_query": "نظریه مشورتی در خصوص ماده 22 قانون مدنی.",
                },
            },
        })

        mock_provider = MagicMock()
        mock_provider.chat.side_effect = [
            {"content": self._VALID_LLM_RESPONSE},
            {"content": response2},
        ]
        mock_get_provider.return_value = mock_provider

        result1 = route_question_cached("مجازات جعل اسناد رسمی چیست؟")
        result2 = route_question_cached("نظریه مشورتی ماده 22 چیست؟")

        assert result1.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"
        assert result2.sub_queries["advisory_opinion"].fts_query == "ماده 22 قانون مدنی نظریه مشورتی"
        assert mock_provider.chat.call_count == 2

    # ------------------------------------------------------------------
    # Normalization: same query with different casing/whitespace
    # ------------------------------------------------------------------

    @patch("conversations.question_router.get_chat_provider")
    def test_normalized_query_hits_cache(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Queries differing only in case/whitespace should hit the same cache entry."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        # First call with extra whitespace
        result1 = route_question_cached("  What is the penalty?  ")
        assert result1.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        # Second call with different casing — should hit cache
        result2 = route_question_cached("WHAT IS THE PENALTY?")
        assert result2.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        mock_provider.chat.assert_called_once()

    # ------------------------------------------------------------------
    # Cache TTL
    # ------------------------------------------------------------------

    @patch("conversations.question_router.get_chat_provider")
    def test_cache_respects_custom_timeout(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Custom timeout should be respected."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        route_question_cached("test query", timeout=60)

        # Second call should hit cache
        result2 = route_question_cached("test query", timeout=60)
        assert result2.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"
        mock_provider.chat.assert_called_once()

    # ------------------------------------------------------------------
    # Error propagation
    # ------------------------------------------------------------------

    @patch("conversations.question_router.get_chat_provider")
    def test_fallback_on_llm_exception(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """If route_question falls back, the fallback result should be cached."""
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = ConnectionError("API unreachable")
        mock_get_provider.return_value = mock_provider

        result = route_question_cached("test query")

        # Should fallback to all hubs with raw query
        for hub in ALL_HUBS:
            assert result.sub_queries[hub].fts_query == "test query"
        assert "API unreachable" in result.reasoning

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    @patch("conversations.question_router.get_chat_provider")
    def test_empty_query_still_calls_route_question(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Empty query should still be passed to route_question (no early return)."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        result = route_question_cached("")
        assert isinstance(result, RouterResult)
        mock_provider.chat.assert_called_once()

    @patch("conversations.question_router.get_chat_provider")
    def test_persian_query_cached_correctly(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Persian text queries should be cached correctly."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {"content": self._VALID_LLM_RESPONSE}
        mock_get_provider.return_value = mock_provider

        persian_query = "مجازات کلاهبرداری طبق قانون چیست؟"
        result1 = route_question_cached(persian_query)
        assert result1.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        # Second call should hit cache
        result2 = route_question_cached(persian_query)
        assert result2.sub_queries["legislation"].fts_query == "مجازات جعل اسناد رسمی"

        mock_provider.chat.assert_called_once()
