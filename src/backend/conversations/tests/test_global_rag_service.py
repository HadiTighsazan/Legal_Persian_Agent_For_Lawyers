"""
Unit tests for the Global RAG Service (Phase 2a — Global RAG).

Tests cover:
- :func:`~conversations.global_rag_service.multi_hub_search`
- :func:`~conversations.global_rag_service.build_global_context`
- :func:`~conversations.global_rag_service.build_global_system_prompt`
- :func:`~conversations.global_rag_service.run_global_rag_query`

All external dependencies (``embed_query``, ``cross_document_hybrid_search``,
``route_question``, ``get_chat_provider``) are mocked using
``unittest.mock.patch``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from conversations.global_rag_service import (
    GlobalRAGServiceException,
    build_global_context,
    build_global_system_prompt,
    multi_hub_search,
    run_global_rag_query,
)
from conversations.question_router import (
    ALL_HUBS,
    HUB_LABELS,
    RouterResult,
    SubQuery,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_router_result() -> RouterResult:
    """Return a RouterResult with all three hubs having queries."""
    return RouterResult(
        sub_queries={
            "legislation": SubQuery(
                fts_query="مجازات جعل اسناد رسمی",
                vector_query="مجازات جعل اسناد رسمی حسب قانون مجازات اسلامی حبس است.",
            ),
            "judicial_precedent": SubQuery(
                fts_query="جعل اسناد رسمی رأی وحدت رویه",
                vector_query="در رویه قضایی مجازات جعل اسناد رسمی تعیین می‌گردد.",
            ),
            "advisory_opinion": SubQuery(
                fts_query="",
                vector_query="",
            ),
        },
        reasoning="Legislation and judicial precedent are relevant.",
    )


@pytest.fixture
def sample_chunks() -> list[dict]:
    """Return sample chunk dicts matching search_service output."""
    return [
        {
            "chunk_id": "chunk-leg-1",
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 3,
            "content": "ماده ۵۲۳ - هرکس در اسناد رسمی جعل نماید به حبس محکوم می‌شود.",
            "relevance_score": 0.95,
            "token_count": 15,
            "metadata": {"law_name": "قانون مجازات اسلامی", "legal_type": "article"},
            "legal_context": "قانون: قانون مجازات اسلامی | ماده: 523",
        },
        {
            "chunk_id": "chunk-leg-2",
            "chunk_index": 1,
            "page_start": 4,
            "page_end": 6,
            "content": "ماده ۵۲۴ - مجازات شروع به جعل اسناد رسمی حبس از یک تا سه سال است.",
            "relevance_score": 0.88,
            "token_count": 12,
            "metadata": {"law_name": "قانون مجازات اسلامی", "legal_type": "article"},
            "legal_context": "قانون: قانون مجازات اسلامی | ماده: 524",
        },
        {
            "chunk_id": "chunk-jud-1",
            "chunk_index": 0,
            "page_start": 10,
            "page_end": 12,
            "content": "رأی وحدت رویه شماره ۷۴۲ - جعل اسناد رسمی جرم مطلق است.",
            "relevance_score": 0.92,
            "token_count": 10,
            "metadata": {"law_name": "رأی وحدت رویه", "legal_type": "article"},
            "legal_context": "رأی وحدت رویه شماره 742",
        },
    ]


# ---------------------------------------------------------------------------
# BuildGlobalSystemPromptTests
# ---------------------------------------------------------------------------


class BuildGlobalSystemPromptTests:
    """Tests for :func:`~conversations.global_rag_service.build_global_system_prompt`."""

    def test_contains_hub_labels(self) -> None:
        """System prompt includes all three hub labels."""
        prompt = build_global_system_prompt()
        assert "Legislation" in prompt
        assert "Judicial Precedent" in prompt
        assert "Advisory Opinions" in prompt
        assert "قوانین مصوب" in prompt
        assert "رویه‌های قضایی" in prompt
        assert "نظریات مشورتی" in prompt

    def test_contains_citation_instructions(self) -> None:
        """System prompt includes [Source N] citation format instructions."""
        prompt = build_global_system_prompt()
        assert "[Source N]" in prompt
        assert "source" in prompt.lower()

    def test_contains_persian_answer_instruction(self) -> None:
        """System prompt instructs answering in Persian."""
        prompt = build_global_system_prompt()
        assert "Persian" in prompt


# ---------------------------------------------------------------------------
# BuildGlobalContextTests
# ---------------------------------------------------------------------------


class BuildGlobalContextTests:
    """Tests for :func:`~conversations.global_rag_service.build_global_context`."""

    def test_formats_chunks_with_hub_sections(
        self,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Context includes per-hub sections with correct headers."""
        hub_results = {
            "legislation": {
                "chunks": sample_chunks[:2],
                "sub_query": sample_router_result.sub_queries["legislation"],
            },
            "judicial_precedent": {
                "chunks": sample_chunks[2:],
                "sub_query": sample_router_result.sub_queries["judicial_precedent"],
            },
        }
        context = build_global_context(hub_results)

        # Should contain hub section headers
        leg_label = HUB_LABELS["legislation"]
        jud_label = HUB_LABELS["judicial_precedent"]
        assert f"=== [{leg_label}] ===" in context
        assert f"=== [{jud_label}] ===" in context

        # Should contain chunk content
        assert "ماده ۵۲۳" in context
        assert "ماده ۵۲۴" in context
        assert "رأی وحدت رویه شماره ۷۴۲" in context

    def test_global_source_numbering(
        self,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Source numbering is global across all hubs."""
        hub_results = {
            "legislation": {
                "chunks": sample_chunks[:2],
                "sub_query": sample_router_result.sub_queries["legislation"],
            },
            "judicial_precedent": {
                "chunks": sample_chunks[2:],
                "sub_query": sample_router_result.sub_queries["judicial_precedent"],
            },
        }
        context = build_global_context(hub_results)

        leg_label = HUB_LABELS["legislation"]
        jud_label = HUB_LABELS["judicial_precedent"]

        # Source 1, 2 from legislation, Source 3 from judicial_precedent
        assert f"[Source 1 | Hub: {leg_label} | Pages 1-3" in context
        assert f"[Source 2 | Hub: {leg_label} | Pages 4-6" in context
        assert f"[Source 3 | Hub: {jud_label} | Pages 10-12" in context

    def test_skips_hubs_with_no_chunks(
        self,
        sample_router_result: RouterResult,
    ) -> None:
        """Hubs with no chunks are skipped in the context."""
        hub_results = {
            "legislation": {
                "chunks": [],
                "sub_query": sample_router_result.sub_queries["legislation"],
            },
            "judicial_precedent": {
                "chunks": [],
                "sub_query": sample_router_result.sub_queries["judicial_precedent"],
            },
        }
        context = build_global_context(hub_results)
        assert context == ""

    def test_skips_missing_hubs(
        self,
    ) -> None:
        """Missing hub keys are gracefully skipped."""
        hub_results: dict = {}
        context = build_global_context(hub_results)
        assert context == ""

    def test_includes_legal_context_in_source_header(
        self,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Source header includes legal_context when available."""
        hub_results = {
            "legislation": {
                "chunks": sample_chunks[:1],
                "sub_query": sample_router_result.sub_queries["legislation"],
            },
        }
        context = build_global_context(hub_results)
        leg_label = HUB_LABELS["legislation"]
        assert f"Hub: {leg_label}" in context
        assert "قانون: قانون مجازات اسلامی | ماده: 523" in context

    @override_settings(RAG_CONTEXT_TOKEN_BUDGET=10)  # 10 tokens = 40 chars
    def test_trims_to_token_budget(
        self,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Context is trimmed to the token budget."""
        hub_results = {
            "legislation": {
                "chunks": sample_chunks[:2],
                "sub_query": sample_router_result.sub_queries["legislation"],
            },
        }
        context = build_global_context(hub_results)
        # With 10 tokens (40 chars), only partial content fits
        assert len(context) <= 40


# ---------------------------------------------------------------------------
# MultiHubSearchTests
# ---------------------------------------------------------------------------


class MultiHubSearchTests:
    """Tests for :func:`~conversations.global_rag_service.multi_hub_search`."""

    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_searches_relevant_hubs(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Only hubs with non-empty queries are searched."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]

        result = multi_hub_search(sample_router_result, top_k_per_hub=5)

        # legislation and judicial_precedent should be searched
        assert mock_cross_search.call_count == 2
        assert "legislation" in result
        assert "judicial_precedent" in result

    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_skips_hub_with_empty_queries(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        sample_router_result: RouterResult,
    ) -> None:
        """Hubs with empty fts_query AND empty vector_query are skipped."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = []

        result = multi_hub_search(sample_router_result, top_k_per_hub=5)

        # advisory_opinion has empty queries, should be skipped
        assert "advisory_opinion" in result
        assert result["advisory_opinion"]["chunks"] == []

    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_passes_correct_hub_type_to_search(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """cross_document_hybrid_search is called with the correct hub_type."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]

        multi_hub_search(sample_router_result, top_k_per_hub=5)

        # Check first call was for legislation
        call_args = mock_cross_search.call_args_list[0][1]
        assert call_args["hub_type"] == "legislation"
        assert call_args["top_k"] == 5

    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_handles_search_exception(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        sample_router_result: RouterResult,
    ) -> None:
        """When search raises an exception, the hub result contains the error."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.side_effect = ValueError("Search failed")

        result = multi_hub_search(sample_router_result, top_k_per_hub=5)

        assert "legislation" in result
        assert result["legislation"]["chunks"] == []
        assert "error" in result["legislation"]
        assert "Search failed" in result["legislation"]["error"]


# ---------------------------------------------------------------------------
# RunGlobalRagQueryTests
# ---------------------------------------------------------------------------


class RunGlobalRagQueryTests:
    """Tests for :func:`~conversations.global_rag_service.run_global_rag_query`."""

    _MOCK_LLM_RESPONSE: dict = {
        "content": (
            "بر اساس قوانین مصوب، مجازات جعل اسناد رسمی حبس است [Source 1]. "
            "بر اساس رویه قضایی، جعل اسناد رسمی جرم مطلق محسوب می‌شود [Source 3]."
        ),
        "token_usage": {
            "prompt_tokens": 500,
            "completion_tokens": 100,
            "total_tokens": 600,
        },
    }

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_full_pipeline_returns_expected_keys(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Full pipeline returns content, sources, token_usage, hub_metadata, raw_chunks."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        mock_provider.chat.return_value = self._MOCK_LLM_RESPONSE
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        assert "content" in result
        assert "sources" in result
        assert "token_usage" in result
        assert "hub_metadata" in result
        assert "raw_chunks" in result
        assert result["content"] == self._MOCK_LLM_RESPONSE["content"]
        assert result["token_usage"] == self._MOCK_LLM_RESPONSE["token_usage"]

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_hub_metadata_contains_per_hub_info(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """hub_metadata contains chunks_count and sub_query for each hub."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        mock_provider.chat.return_value = self._MOCK_LLM_RESPONSE
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        hub_metadata = result["hub_metadata"]
        assert "legislation" in hub_metadata
        assert "judicial_precedent" in hub_metadata
        assert "advisory_opinion" in hub_metadata
        assert "chunks_count" in hub_metadata["legislation"]
        assert "sub_query" in hub_metadata["legislation"]
        assert "fts_query" in hub_metadata["legislation"]["sub_query"]

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_passes_conversation_history(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Conversation history is passed to the chat provider."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        mock_provider.chat.return_value = self._MOCK_LLM_RESPONSE
        mock_get_provider.return_value = mock_provider

        history = [
            {"role": "user", "content": "Prior question"},
            {"role": "assistant", "content": "Prior answer"},
        ]

        run_global_rag_query(
            question="Follow-up question",
            conversation_history=history,
            top_k_per_hub=5,
        )

        # Check that history was included in the messages
        call_args = mock_provider.chat.call_args[1]
        messages = call_args["messages"]
        # Find the history messages in the messages array
        history_messages = [
            m for m in messages
            if m["role"] in ("user", "assistant") and m["content"] in ("Prior question", "Prior answer")
        ]
        assert len(history_messages) == 2

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_route_question_failure_raises_exception(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
    ) -> None:
        """When route_question fails, GlobalRAGServiceException is raised."""
        mock_route.side_effect = Exception("Routing failed")

        with pytest.raises(GlobalRAGServiceException) as exc_info:
            run_global_rag_query("test question")
        assert "Question routing failed" in str(exc_info.value)

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_chat_provider_failure_raises_exception(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """When chat provider fails, GlobalRAGServiceException is raised."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = ConnectionError("API error")
        mock_get_provider.return_value = mock_provider

        with pytest.raises(GlobalRAGServiceException) as exc_info:
            run_global_rag_query("test question")
        assert "Chat provider API call failed" in str(exc_info.value)
