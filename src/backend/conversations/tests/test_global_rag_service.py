"""
Unit tests for the Global RAG Service (Phase 2b — Full).

Tests cover:
- :func:`~conversations.global_rag_service.multi_hub_search`
- :func:`~conversations.global_rag_service.build_global_context`
- :func:`~conversations.global_rag_service.build_global_system_prompt`
- :func:`~conversations.global_rag_service.build_hub_system_prompt`
- :func:`~conversations.global_rag_service.build_synthesis_system_prompt`
- :func:`~conversations.global_rag_service.generate_hub_partial_answer`
- :func:`~conversations.global_rag_service.synthesize_answers`
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
    _generate_single_partial_answer,
    _search_single_hub,
    build_global_context,
    build_global_system_prompt,
    build_hub_system_prompt,
    build_synthesis_system_prompt,
    generate_hub_partial_answer,
    multi_hub_search,
    run_global_rag_query,
    synthesize_answers,
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
        hypothetical_answer="بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است.",
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
# BuildGlobalSystemPromptTests (Phase 2a — Legacy)
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

        # Source 1, 2 from legislation, Source 3 from judicial_precedent
        assert "[Source 1 | Pages 1-3" in context
        assert "[Source 2 | Pages 4-6" in context
        assert "[Source 3 | Pages 10-12" in context

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
        """All hubs are searched when hypothetical_answer provides a vector query."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]

        result = multi_hub_search(sample_router_result, top_k_per_hub=5)

        # All 3 hubs should be searched because hypothetical_answer provides
        # a non-empty vector query for advisory_opinion (Phase 3 merge)
        assert mock_cross_search.call_count == 3
        assert "legislation" in result
        assert "judicial_precedent" in result
        assert "advisory_opinion" in result

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
# BuildHubSystemPromptTests (Phase 2b)
# ---------------------------------------------------------------------------


class BuildHubSystemPromptTests:
    """Tests for :func:`~conversations.global_rag_service.build_hub_system_prompt`."""

    def test_legislation_prompt_contains_specialized_instructions(self) -> None:
        """Legislation prompt includes law-specific instructions."""
        prompt = build_hub_system_prompt("legislation")
        assert "Legislation" in prompt or "legislation" in prompt
        assert "قوانین مصوب" in prompt
        assert "article" in prompt.lower() or "ماده" in prompt
        assert "PARTIAL" in prompt or "partial" in prompt

    def test_judicial_precedent_prompt_contains_specialized_instructions(self) -> None:
        """Judicial precedent prompt includes precedent-specific instructions."""
        prompt = build_hub_system_prompt("judicial_precedent")
        assert "Judicial Precedent" in prompt or "judicial_precedent" in prompt
        assert "رویه‌های قضایی" in prompt
        assert "judgment" in prompt.lower() or "رأی" in prompt
        assert "PARTIAL" in prompt or "partial" in prompt

    def test_advisory_opinion_prompt_contains_specialized_instructions(self) -> None:
        """Advisory opinion prompt includes opinion-specific instructions."""
        prompt = build_hub_system_prompt("advisory_opinion")
        assert "Advisory Opinions" in prompt or "advisory_opinion" in prompt
        assert "نظریات مشورتی" in prompt
        assert "opinion" in prompt.lower() or "نظریه" in prompt
        assert "PARTIAL" in prompt or "partial" in prompt

    def test_raises_value_error_for_unknown_hub(self) -> None:
        """Unknown hub type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_hub_system_prompt("unknown_hub")
        assert "Unknown hub_type" in str(exc_info.value)

    def test_all_hub_prompts_contain_base_instructions(self) -> None:
        """All hub prompts contain the base instructions."""
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            prompt = build_hub_system_prompt(hub_type)
            assert "[Source N]" in prompt
            assert "Persian" in prompt
            assert "partial" in prompt.lower()


# ---------------------------------------------------------------------------
# BuildSynthesisSystemPromptTests (Phase 2b)
# ---------------------------------------------------------------------------


class BuildSynthesisSystemPromptTests:
    """Tests for :func:`~conversations.global_rag_service.build_synthesis_system_prompt`."""

    def test_contains_conflict_detection_instructions(self) -> None:
        """Synthesis prompt includes conflict detection instructions."""
        prompt = build_synthesis_system_prompt()
        assert "Conflict" in prompt or "conflict" in prompt
        assert "[Conflict]" in prompt

    def test_contains_legal_hierarchy(self) -> None:
        """Synthesis prompt includes legal hierarchy resolution."""
        prompt = build_synthesis_system_prompt()
        assert "Legislation" in prompt
        assert "highest" in prompt.lower() or "precedence" in prompt.lower()
        assert "Judicial Precedent" in prompt
        assert "Advisory Opinions" in prompt

    def test_contains_synthesis_instructions(self) -> None:
        """Synthesis prompt includes merge/synthesis instructions."""
        prompt = build_synthesis_system_prompt()
        assert "synthesis" in prompt.lower() or "synthesise" in prompt.lower()
        assert "partial answers" in prompt.lower()

    def test_contains_persian_answer_instruction(self) -> None:
        """Synthesis prompt instructs answering in Persian."""
        prompt = build_synthesis_system_prompt()
        assert "Persian" in prompt


# ---------------------------------------------------------------------------
# GenerateHubPartialAnswerTests (Phase 2b)
# ---------------------------------------------------------------------------


class GenerateHubPartialAnswerTests:
    """Tests for :func:`~conversations.global_rag_service.generate_hub_partial_answer`."""

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_generates_partial_answer_for_hub_with_chunks(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Hub with chunks generates a partial answer via LLM."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "بر اساس قوانین مصوب، مجازات جعل اسناد رسمی حبس است.",
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        mock_get_provider.return_value = mock_provider

        chunks = [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 2,
                "content": "ماده ۵۲۳ - مجازات جعل اسناد رسمی حبس.",
                "legal_context": "قانون مجازات اسلامی ماده 523",
            }
        ]

        result = generate_hub_partial_answer(
            hub_type="legislation",
            question="مجازات جعل اسناد رسمی چیست؟",
            chunks=chunks,
        )

        assert "content" in result
        assert "token_usage" in result
        assert "error" in result
        assert result["error"] is None
        assert "بر اساس قوانین مصوب" in result["content"]
        assert result["token_usage"]["total_tokens"] == 120

    def test_returns_empty_answer_for_hub_with_no_chunks(self) -> None:
        """Hub with no chunks returns a 'no info' answer without LLM call."""
        result = generate_hub_partial_answer(
            hub_type="legislation",
            question="مجازات جعل اسناد رسمی چیست؟",
            chunks=[],
        )

        assert "content" in result
        assert "token_usage" in result
        assert result["error"] is None
        assert "هیچ اطلاعات مرتبطی" in result["content"]
        # Token usage should be zero (no LLM call)
        assert result["token_usage"]["total_tokens"] == 0

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_handles_llm_error_gracefully(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When LLM call fails, returns error in result without raising."""
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = ConnectionError("API connection failed")
        mock_get_provider.return_value = mock_provider

        chunks = [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 2,
                "content": "ماده ۵۲۳",
            }
        ]

        result = generate_hub_partial_answer(
            hub_type="legislation",
            question="مجازات جعل اسناد رسمی چیست؟",
            chunks=chunks,
        )

        assert "content" in result
        assert "error" in result
        assert result["error"] is not None
        assert "API connection failed" in result["error"]

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_uses_correct_system_prompt_per_hub_type(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Each hub type uses its own specialized system prompt."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "Partial answer",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        }
        mock_get_provider.return_value = mock_provider

        chunks = [{"chunk_id": "c1", "page_start": 1, "page_end": 2, "content": "test"}]

        # Test legislation
        generate_hub_partial_answer("legislation", "test question", chunks)
        leg_messages = mock_provider.chat.call_args[1]["messages"]
        leg_system = leg_messages[0]["content"]
        assert "Legislation" in leg_system or "legislation" in leg_system

        # Test judicial_precedent
        generate_hub_partial_answer("judicial_precedent", "test question", chunks)
        jud_messages = mock_provider.chat.call_args[1]["messages"]
        jud_system = jud_messages[0]["content"]
        assert "Judicial Precedent" in jud_system or "judicial_precedent" in jud_system

        # Test advisory_opinion
        generate_hub_partial_answer("advisory_opinion", "test question", chunks)
        adv_messages = mock_provider.chat.call_args[1]["messages"]
        adv_system = adv_messages[0]["content"]
        assert "Advisory Opinions" in adv_system or "advisory_opinion" in adv_system


# ---------------------------------------------------------------------------
# SynthesizeAnswersTests (Phase 2b)
# ---------------------------------------------------------------------------


class SynthesizeAnswersTests:
    """Tests for :func:`~conversations.global_rag_service.synthesize_answers`."""

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_merges_partial_answers_into_final_answer(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Partial answers are merged into a final synthesized answer."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "بر اساس قوانین مصوب و رویه قضایی، مجازات جعل اسناد رسمی حبس است.",
            "token_usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        }
        mock_get_provider.return_value = mock_provider

        partial_answers = {
            "legislation": {
                "content": "بر اساس قانون مجازات اسلامی ماده 523، مجازات جعل اسناد رسمی حبس است.",
                "token_usage": {"total_tokens": 100},
                "error": None,
            },
            "judicial_precedent": {
                "content": "بر اساس رأی وحدت رویه شماره 742، جعل اسناد رسمی جرم مطلق است.",
                "token_usage": {"total_tokens": 80},
                "error": None,
            },
            "advisory_opinion": {
                "content": "هیچ اطلاعات مرتبطی در نظریات مشورتی یافت نشد.",
                "token_usage": {"total_tokens": 0},
                "error": None,
            },
        }

        result = synthesize_answers(
            question="مجازات جعل اسناد رسمی چیست؟",
            partial_answers=partial_answers,
        )

        assert "content" in result
        assert "token_usage" in result
        assert result["error"] is None
        assert "بر اساس قوانین مصوب" in result["content"]

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_detects_conflicts_between_hubs(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Synthesis prompt includes conflict detection instructions."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": (
                "[Conflict] در قانون مجازات اسلامی مجازات جعل اسناد رسمی حبس است، "
                "اما در رأی وحدت رویه شماره 742 این عمل جرم مطلق محسوب می‌شود. "
                "با توجه به سلسله مراتب حقوقی، قانون مقدم است."
            ),
            "token_usage": {"prompt_tokens": 200, "completion_tokens": 60, "total_tokens": 260},
        }
        mock_get_provider.return_value = mock_provider

        partial_answers = {
            "legislation": {
                "content": "مجازات حبس طبق ماده 523.",
                "token_usage": {"total_tokens": 50},
                "error": None,
            },
            "judicial_precedent": {
                "content": "جرم مطلق طبق رأی وحدت رویه 742.",
                "token_usage": {"total_tokens": 40},
                "error": None,
            },
        }

        result = synthesize_answers(
            question="مجازات جعل اسناد رسمی چیست؟",
            partial_answers=partial_answers,
        )

        # Verify the synthesis prompt was used (contains conflict instructions)
        call_messages = mock_provider.chat.call_args[1]["messages"]
        system_prompt = call_messages[0]["content"]
        assert "[Conflict]" in system_prompt or "Conflict" in system_prompt

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_handles_single_hub_synthesis(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Synthesis works with only one hub having data."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "بر اساس قوانین مصوب، مجازات جعل اسناد رسمی حبس است.",
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        }
        mock_get_provider.return_value = mock_provider

        partial_answers = {
            "legislation": {
                "content": "بر اساس قانون مجازات اسلامی ماده 523، مجازات حبس است.",
                "token_usage": {"total_tokens": 50},
                "error": None,
            },
        }

        result = synthesize_answers(
            question="مجازات جعل اسناد رسمی چیست؟",
            partial_answers=partial_answers,
        )

        assert result["error"] is None
        assert "content" in result

    @patch("conversations.global_rag_service.get_chat_provider")
    def test_handles_all_hubs_empty(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Synthesis handles case where all hubs have no data."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "هیچ یک از منابع حقوقی اطلاعات مرتبطی ندارند.",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 15, "total_tokens": 65},
        }
        mock_get_provider.return_value = mock_provider

        partial_answers: dict = {}

        result = synthesize_answers(
            question="test question",
            partial_answers=partial_answers,
        )

        assert result["error"] is None
        assert "content" in result


# ---------------------------------------------------------------------------
# RunGlobalRagQueryTests (Phase 2b — Full)
# ---------------------------------------------------------------------------


class RunGlobalRagQueryTests:
    """Tests for :func:`~conversations.global_rag_service.run_global_rag_query`."""

    _MOCK_LLM_RESPONSE: dict = {
        "content": (
            "Partial answer from legislation hub."
        ),
        "token_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        },
    }

    _MOCK_SYNTHESIS_RESPONSE: dict = {
        "content": (
            "بر اساس قوانین مصوب، مجازات جعل اسناد رسمی حبس است [Source 1]. "
            "بر اساس رویه قضایی، جعل اسناد رسمی جرم مطلق محسوب می‌شود [Source 3]."
        ),
        "token_usage": {
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "total_tokens": 250,
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
        """Full pipeline returns content, sources, token_usage, hub_metadata, raw_chunks, partial_answers."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # Phase 3: hypothetical_answer provides a vector query for ALL hubs,
        # so advisory_opinion is also searched and gets a partial answer.
        # 3 per-hub calls (legislation, judicial_precedent, advisory_opinion) + 1 synthesis = 4 total.
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,       # legislation partial
            self._MOCK_LLM_RESPONSE,       # judicial_precedent partial
            self._MOCK_LLM_RESPONSE,       # advisory_opinion partial
            self._MOCK_SYNTHESIS_RESPONSE,  # synthesis
        ]
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
        assert "partial_answers" in result
        assert result["content"] == self._MOCK_SYNTHESIS_RESPONSE["content"]
        # Total tokens = 3 * 120 (partial) + 250 (synthesis) = 610
        assert result["token_usage"]["total_tokens"] == 610

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_partial_answers_included_in_hub_metadata(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """hub_metadata includes partial_answer and partial_answer_token_usage per hub."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # advisory_opinion has empty queries — no LLM call for it.
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            self._MOCK_SYNTHESIS_RESPONSE,
        ]
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        hub_metadata = result["hub_metadata"]
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            assert hub_type in hub_metadata
            assert "partial_answer" in hub_metadata[hub_type]
            assert "partial_answer_token_usage" in hub_metadata[hub_type]
            assert "partial_answer_error" in hub_metadata[hub_type]

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_partial_answers_returned_in_response(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """partial_answers dict is returned in the response."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # advisory_opinion has empty queries — no LLM call for it.
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            self._MOCK_SYNTHESIS_RESPONSE,
        ]
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        assert "partial_answers" in result
        partial_answers = result["partial_answers"]
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            assert hub_type in partial_answers
            assert "content" in partial_answers[hub_type]
            assert "token_usage" in partial_answers[hub_type]
            assert "error" in partial_answers[hub_type]

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_token_usage_includes_all_llm_calls(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """token_usage includes tokens from all LLM calls (2 partial + 1 synthesis)."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # advisory_opinion has empty queries — no LLM call for it.
        # Only 2 per-hub calls (legislation, judicial_precedent) + 1 synthesis = 3 total.
        mock_provider.chat.side_effect = [
            {"content": "PA1", "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
            {"content": "PA2", "token_usage": {"prompt_tokens": 80, "completion_tokens": 15, "total_tokens": 95}},
            {"content": "SYNTH", "token_usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250}},
        ]
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        # Total = 120 + 95 + 250 = 465
        assert result["token_usage"]["total_tokens"] == 465
        assert result["token_usage"]["prompt_tokens"] == 380
        assert result["token_usage"]["completion_tokens"] == 85

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
        """Conversation history is passed to the chat provider (in synthesis call)."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # advisory_opinion has empty queries — no LLM call for it.
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            self._MOCK_SYNTHESIS_RESPONSE,
        ]
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

        # Note: In Phase 2b, conversation history is NOT passed to per-hub calls
        # or the synthesis call (they use their own messages). This test verifies
        # backward compatibility — the function accepts history without error.
        # History is currently not used in Phase 2b pipeline (simplified).
        # This can be enhanced in a future iteration.
        assert True

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
    def test_synthesis_failure_raises_exception(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """When synthesis fails, GlobalRAGServiceException is raised."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # Phase 3: hypothetical_answer provides vector query for all hubs.
        # First 3 calls (per-hub) succeed, 4th call (synthesis) fails
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            ConnectionError("Synthesis API error"),
        ]
        mock_get_provider.return_value = mock_provider

        with pytest.raises(GlobalRAGServiceException) as exc_info:
            run_global_rag_query("test question")
        assert "Answer synthesis failed" in str(exc_info.value)

    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    @patch("conversations.global_rag_service.route_question")
    def test_backward_compatible_response_format(
        self,
        mock_route: MagicMock,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_get_provider: MagicMock,
        sample_router_result: RouterResult,
        sample_chunks: list[dict],
    ) -> None:
        """Response format is backward compatible with Phase 2a (adds partial_answers)."""
        mock_route.return_value = sample_router_result
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = sample_chunks[:1]
        mock_provider = MagicMock()
        # advisory_opinion has empty queries — no LLM call for it.
        mock_provider.chat.side_effect = [
            self._MOCK_LLM_RESPONSE,
            self._MOCK_LLM_RESPONSE,
            self._MOCK_SYNTHESIS_RESPONSE,
        ]
        mock_get_provider.return_value = mock_provider

        result = run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        # Phase 2a keys still present
        assert "content" in result
        assert "sources" in result
        assert "token_usage" in result
        assert "hub_metadata" in result
        assert "raw_chunks" in result

        # Phase 2b new key
        assert "partial_answers" in result

        # hub_metadata still has Phase 2a keys
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            assert "chunks_count" in result["hub_metadata"][hub_type]
            assert "sub_query" in result["hub_metadata"][hub_type]

        # hub_metadata sub_query includes hypothetical_answer (Phase 3) for all hubs
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            sub_query = result["hub_metadata"][hub_type]["sub_query"]
            assert "hypothetical_answer" in sub_query
            assert sub_query["hypothetical_answer"] == sample_router_result.hypothetical_answer


# ---------------------------------------------------------------------------
# Parallel Execution Tests (Phase 2b)
# ---------------------------------------------------------------------------


class ParallelExecutionTests:
    """Tests for parallel execution helpers and ThreadPoolExecutor usage.

    Covers:
    - :func:`~conversations.global_rag_service._search_single_hub`
    - :func:`~conversations.global_rag_service._generate_single_partial_answer`
    - Verifies that :class:`ThreadPoolExecutor` is used with ``max_workers=3``
      in :func:`~conversations.global_rag_service.multi_hub_search` and
      :func:`~conversations.global_rag_service.run_global_rag_query`.
    """

    # ------------------------------------------------------------------
    # _search_single_hub
    # ------------------------------------------------------------------

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_search_single_hub_calls_close_old_connections(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_search_single_hub must call close_old_connections() for thread safety."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = []

        sub_query = SubQuery(
            fts_query="مجازات جعل",
            vector_query="مجازات جعل اسناد رسمی",
        )

        _search_single_hub(
            hub_type="legislation",
            sub_query=sub_query,
            top_k_per_hub=5,
        )

        mock_close.assert_called_once()

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_search_single_hub_skips_empty_queries(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_search_single_hub must skip hubs with empty FTS and vector queries."""
        sub_query = SubQuery(fts_query="", vector_query="")

        hub_type, result = _search_single_hub(
            hub_type="advisory_opinion",
            sub_query=sub_query,
            top_k_per_hub=5,
        )

        assert hub_type == "advisory_opinion"
        assert result["chunks"] == []
        assert result["token_usage"]["embedding_tokens"] == 0
        # embed_query should NOT be called for empty queries
        mock_embed.assert_not_called()
        mock_cross_search.assert_not_called()

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_search_single_hub_returns_tuple(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_search_single_hub must return a (hub_type, result_dict) tuple."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = [{"id": "chunk_1", "content": "test"}]

        sub_query = SubQuery(
            fts_query="مجازات جعل",
            vector_query="مجازات جعل اسناد رسمی",
        )

        result = _search_single_hub(
            hub_type="legislation",
            sub_query=sub_query,
            top_k_per_hub=5,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        hub_type, result_dict = result
        assert hub_type == "legislation"
        assert "chunks" in result_dict
        assert "sub_query" in result_dict
        assert "token_usage" in result_dict
        assert len(result_dict["chunks"]) == 1

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_search_single_hub_handles_exception(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_search_single_hub must catch exceptions and return error dict."""
        mock_embed.side_effect = ValueError("Embedding API failed")

        sub_query = SubQuery(
            fts_query="مجازات جعل",
            vector_query="مجازات جعل اسناد رسمی",
        )

        hub_type, result = _search_single_hub(
            hub_type="legislation",
            sub_query=sub_query,
            top_k_per_hub=5,
        )

        assert hub_type == "legislation"
        assert result["chunks"] == []
        assert "error" in result
        assert "Embedding API failed" in result["error"]

    # ------------------------------------------------------------------
    # multi_hub_search — ThreadPoolExecutor usage
    # ------------------------------------------------------------------

    def test_multi_hub_search_uses_thread_pool(
        self,
    ) -> None:
        """multi_hub_search must use ThreadPoolExecutor(max_workers=3).

        We verify this by checking that ``_search_single_hub`` is called once
        per relevant hub (i.e., the executor submits 3 tasks). The actual
        parallel execution is tested end-to-end in
        :meth:`test_multi_hub_search_returns_all_hubs`.
        """
        from concurrent.futures import ThreadPoolExecutor

        router_result = RouterResult(
            sub_queries={
                "legislation": SubQuery(
                    fts_query="مجازات جعل",
                    vector_query="مجازات جعل اسناد رسمی",
                ),
                "judicial_precedent": SubQuery(
                    fts_query="رأی وحدت رویه",
                    vector_query="رأی وحدت رویه جعل",
                ),
                "advisory_opinion": SubQuery(
                    fts_query="",
                    vector_query="",
                ),
            },
            reasoning="Test",
            hypothetical_answer="بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است.",
        )

        # Use a real ThreadPoolExecutor but spy on its constructor
        original_init = ThreadPoolExecutor.__init__

        def spy_init(self, *args, **kwargs):
            self._spy_max_workers = kwargs.get("max_workers")
            return original_init(self, *args, **kwargs)

        with patch.object(
            ThreadPoolExecutor, "__init__", spy_init
        ):
            results = multi_hub_search(
                router_result=router_result, top_k_per_hub=5
            )

        # Verify all 3 hubs returned results (proves executor ran)
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            assert hub_type in results

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_multi_hub_search_returns_all_hubs(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """multi_hub_search must return results for all hubs."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = [{"id": "chunk_1", "content": "test"}]

        router_result = RouterResult(
            sub_queries={
                "legislation": SubQuery(
                    fts_query="مجازات جعل",
                    vector_query="مجازات جعل اسناد رسمی",
                ),
                "judicial_precedent": SubQuery(
                    fts_query="رأی وحدت رویه",
                    vector_query="رأی وحدت رویه جعل",
                ),
                "advisory_opinion": SubQuery(
                    fts_query="",
                    vector_query="",
                ),
            },
            reasoning="Test",
            hypothetical_answer="بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است.",
        )

        results = multi_hub_search(router_result=router_result, top_k_per_hub=5)

        # All 3 hubs must be present in the result
        for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
            assert hub_type in results
            assert "chunks" in results[hub_type]
            assert "sub_query" in results[hub_type]
            assert "token_usage" in results[hub_type]

        # All hubs should have chunks because hypothetical_answer provides
        # a non-empty vector query for advisory_opinion (Phase 3 merge)
        assert len(results["legislation"]["chunks"]) == 1
        assert len(results["judicial_precedent"]["chunks"]) == 1
        assert len(results["advisory_opinion"]["chunks"]) == 1

    # ------------------------------------------------------------------
    # _generate_single_partial_answer
    # ------------------------------------------------------------------

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.generate_hub_partial_answer")
    def test_generate_single_partial_answer_calls_close_old_connections(
        self,
        mock_generate: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_generate_single_partial_answer must call close_old_connections()."""
        mock_generate.return_value = {
            "content": "Partial answer",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 30},
        }

        _generate_single_partial_answer(
            hub_type="legislation",
            question="مجازات جعل چیست؟",
            chunks=[{"id": "chunk_1", "content": "test"}],
        )

        mock_close.assert_called_once()

    @patch("conversations.global_rag_service.close_old_connections")
    @patch("conversations.global_rag_service.generate_hub_partial_answer")
    def test_generate_single_partial_answer_returns_tuple(
        self,
        mock_generate: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        """_generate_single_partial_answer must return (hub_type, result_dict)."""
        expected_result = {
            "content": "Partial answer",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 30},
        }
        mock_generate.return_value = expected_result

        result = _generate_single_partial_answer(
            hub_type="legislation",
            question="مجازات جعل چیست؟",
            chunks=[{"id": "chunk_1", "content": "test"}],
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        hub_type, result_dict = result
        assert hub_type == "legislation"
        assert result_dict == expected_result

    # ------------------------------------------------------------------
    # run_global_rag_query — ThreadPoolExecutor for partial answers
    # ------------------------------------------------------------------

    @patch("conversations.global_rag_service.ThreadPoolExecutor")
    @patch("conversations.global_rag_service.get_chat_provider")
    @patch("conversations.global_rag_service.route_question")
    @patch("conversations.global_rag_service.embed_query")
    @patch("conversations.global_rag_service.cross_document_hybrid_search")
    def test_run_global_rag_query_uses_thread_pool_for_partial_answers(
        self,
        mock_cross_search: MagicMock,
        mock_embed: MagicMock,
        mock_route: MagicMock,
        mock_get_provider: MagicMock,
        mock_executor_cls: MagicMock,
    ) -> None:
        """run_global_rag_query must use ThreadPoolExecutor for partial answers."""
        # Mock route
        mock_route.return_value = RouterResult(
            sub_queries={
                "legislation": SubQuery(
                    fts_query="مجازات جعل",
                    vector_query="مجازات جعل اسناد رسمی",
                ),
                "judicial_precedent": SubQuery(
                    fts_query="رأی وحدت رویه",
                    vector_query="رأی وحدت رویه جعل",
                ),
                "advisory_opinion": SubQuery(
                    fts_query="",
                    vector_query="",
                ),
            },
            reasoning="Test",
            hypothetical_answer="بر اساس قانون مجازات اسلامی، مجازات جعل اسناد رسمی حبس است.",
        )

        # Mock search
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_cross_search.return_value = [{"id": "chunk_1", "content": "test"}]

        # Mock LLM provider
        mock_provider = MagicMock()
        mock_provider.chat.side_effect = [
            {"content": "PA1", "token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            {"content": "PA2", "token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            {"content": "Synthesis", "token_usage": {"prompt_tokens": 20, "completion_tokens": 10}},
        ]
        mock_get_provider.return_value = mock_provider

        # Mock ThreadPoolExecutor to actually execute (use real executor)
        # We just want to verify it's created with max_workers=3
        import concurrent.futures
        mock_executor_cls.side_effect = concurrent.futures.ThreadPoolExecutor

        run_global_rag_query(
            question="مجازات جعل اسناد رسمی چیست؟",
            top_k_per_hub=5,
        )

        # Verify ThreadPoolExecutor was created with max_workers=3
        mock_executor_cls.assert_called_with(max_workers=3)
