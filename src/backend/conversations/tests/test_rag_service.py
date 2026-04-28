"""
Unit tests for the RAG service layer.

Tests cover:
- :func:`~conversations.rag_service.build_context`
- :func:`~conversations.rag_service.build_system_prompt`
- :func:`~conversations.rag_service.extract_citations`
- :func:`~conversations.rag_service.run_rag_query`

All external dependencies (``embed_query``, ``search_chunks``, ``OpenAI``)
are mocked using ``unittest.mock.patch``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from conversations.rag_service import (
    RAGServiceException,
    build_context,
    build_system_prompt,
    extract_citations,
    run_rag_query,
)

# ---------------------------------------------------------------------------
# Fixtures — reusable sample chunks
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_chunks() -> list[dict]:
    """Return a list of 3 sample chunk dicts matching search_service output."""
    return [
        {
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 3,
            "content": "The quick brown fox jumps over the lazy dog.",
            "relevance_score": 0.95,
            "token_count": 10,
            "metadata": {},
        },
        {
            "chunk_id": "chunk-2",
            "chunk_index": 1,
            "page_start": 4,
            "page_end": 6,
            "content": "Python is a high-level programming language.",
            "relevance_score": 0.88,
            "token_count": 8,
            "metadata": {},
        },
        {
            "chunk_id": "chunk-3",
            "chunk_index": 2,
            "page_start": 7,
            "page_end": 9,
            "content": "Machine learning models require large amounts of data.",
            "relevance_score": 0.72,
            "token_count": 12,
            "metadata": {},
        },
    ]


# ---------------------------------------------------------------------------
# BuildContextTests
# ---------------------------------------------------------------------------


class BuildContextTests:
    """Tests for :func:`~conversations.rag_service.build_context`."""

    def test_formats_chunks_correctly(self, sample_chunks: list[dict]) -> None:
        """Verify each chunk is formatted with [Source N | Pages X-Y] header."""
        result = build_context(sample_chunks)

        assert "[Source 1 | Pages 1-3]" in result
        assert "[Source 2 | Pages 4-6]" in result
        assert "[Source 3 | Pages 7-9]" in result
        assert "The quick brown fox jumps over the lazy dog." in result
        assert "Python is a high-level programming language." in result
        assert "Machine learning models require large amounts of data." in result

    @override_settings(RAG_CONTEXT_TOKEN_BUDGET=10)  # 10 tokens = 40 chars
    def test_trims_to_token_budget(self, sample_chunks: list[dict]) -> None:
        """Provide chunks exceeding budget, verify truncation."""
        result = build_context(sample_chunks)

        # With 10 tokens (40 chars), only the first chunk header + partial content fits
        assert "[Source 1 | Pages 1-3]" in result
        # The second chunk should not appear (or only partially)
        assert len(result) <= 40

    def test_empty_chunks_list(self) -> None:
        """Empty list returns empty string."""
        result = build_context([])
        assert result == ""

    def test_single_chunk_within_budget(self, sample_chunks: list[dict]) -> None:
        """Single chunk under budget returned as-is."""
        single = [sample_chunks[0]]
        result = build_context(single)

        assert "[Source 1 | Pages 1-3]" in result
        assert "The quick brown fox jumps over the lazy dog." in result
        assert result == (
            "[Source 1 | Pages 1-3]\n"
            "The quick brown fox jumps over the lazy dog."
        )


# ---------------------------------------------------------------------------
# BuildSystemPromptTests
# ---------------------------------------------------------------------------


class BuildSystemPromptTests:
    """Tests for :func:`~conversations.rag_service.build_system_prompt`."""

    def test_includes_document_title(self) -> None:
        """Prompt contains the document title."""
        title = "My Test Document"
        prompt = build_system_prompt(title)
        assert title in prompt

    def test_instructions_present(self) -> None:
        """Prompt includes key instructions."""
        prompt = build_system_prompt("Doc")

        # Must instruct to answer only from context
        assert "ONLY on the context" in prompt or "ONLY from the context" in prompt

        # Must instruct to say "don't have enough information"
        assert "don't have enough information" in prompt

        # Must instruct to cite sources
        assert "[Source N]" in prompt


# ---------------------------------------------------------------------------
# ExtractCitationsTests
# ---------------------------------------------------------------------------


class ExtractCitationsTests:
    """Tests for :func:`~conversations.rag_service.extract_citations`."""

    def test_cited_sources_are_extracted(self, sample_chunks: list[dict]) -> None:
        """Response cites [Source 1] and [Source 3], only those are returned."""
        content = (
            "According to [Source 1], the fox jumped. "
            "Additionally, [Source 3] mentions machine learning."
        )
        citations = extract_citations(content, sample_chunks)

        assert len(citations) == 2
        assert citations[0]["chunk_id"] == "chunk-1"
        assert citations[1]["chunk_id"] == "chunk-3"

    def test_uncited_sources_ignored(self, sample_chunks: list[dict]) -> None:
        """Chunks exist but are not cited, returns empty list."""
        content = "This response does not cite any sources."
        citations = extract_citations(content, sample_chunks)
        assert citations == []

    def test_malformed_references_ignored(self, sample_chunks: list[dict]) -> None:
        """[Source abc], [Source], [abc] are ignored."""
        content = (
            "Some text [Source abc] more text [Source] "
            "and [abc] and [Source 1] valid."
        )
        citations = extract_citations(content, sample_chunks)
        assert len(citations) == 1
        assert citations[0]["chunk_id"] == "chunk-1"

    def test_out_of_range_source_ignored(self, sample_chunks: list[dict]) -> None:
        """[Source 99] when only 3 chunks exist is ignored."""
        content = "Reference [Source 99] is out of range."
        citations = extract_citations(content, sample_chunks)
        assert citations == []

    def test_multiple_citations_same_source(self, sample_chunks: list[dict]) -> None:
        """Multiple [Source 1] references return one citation."""
        content = (
            "First mention [Source 1] and second mention [Source 1] "
            "and third [Source 1]."
        )
        citations = extract_citations(content, sample_chunks)
        assert len(citations) == 1
        assert citations[0]["chunk_id"] == "chunk-1"

    def test_empty_content(self, sample_chunks: list[dict]) -> None:
        """Empty string returns empty list."""
        citations = extract_citations("", sample_chunks)
        assert citations == []


# ---------------------------------------------------------------------------
# RunRagQueryTests
# ---------------------------------------------------------------------------


class RunRagQueryTests:
    """Tests for :func:`~conversations.rag_service.run_rag_query`."""

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_normal_response(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Full pipeline returns correct result dict structure."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = [
            {
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 3,
                "content": "Sample content for testing.",
                "relevance_score": 0.95,
                "token_count": 10,
                "metadata": {},
            }
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "Based on the context, [Source 1] provides relevant information."
        )
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        result = run_rag_query(
            question="What is the document about?",
            document_id="doc-123",
            top_k=5,
        )

        # Assert
        assert "content" in result
        assert "sources" in result
        assert "token_usage" in result
        assert "raw_chunks" in result
        assert len(result["sources"]) == 1
        assert result["sources"][0]["chunk_id"] == "chunk-1"
        assert result["token_usage"]["total_tokens"] == 150
        assert result["content"] == (
            "Based on the context, [Source 1] provides relevant information."
        )

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_citation_extraction_integration(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """OpenAI returns content with [Source 1], verify sources list is populated."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = [
            {
                "chunk_id": "chunk-a",
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 2,
                "content": "First chunk content.",
                "relevance_score": 0.90,
                "token_count": 5,
                "metadata": {},
            },
            {
                "chunk_id": "chunk-b",
                "chunk_index": 1,
                "page_start": 3,
                "page_end": 4,
                "content": "Second chunk content.",
                "relevance_score": 0.80,
                "token_count": 5,
                "metadata": {},
            },
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "The answer is in [Source 1] and also [Source 2]."
        )
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 70
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        result = run_rag_query(
            question="Test question?",
            document_id="doc-456",
        )

        # Assert
        assert len(result["sources"]) == 2
        assert result["sources"][0]["chunk_id"] == "chunk-a"
        assert result["sources"][1]["chunk_id"] == "chunk-b"

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_history_truncation(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Provide 20 history turns, verify only last RAG_MAX_HISTORY_TURNS (10) are included."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = []

        # Create 20 turns of history (40 messages)
        history: list[dict[str, str]] = []
        for i in range(20):
            history.append({"role": "user", "content": f"Question {i}"})
            history.append({"role": "assistant", "content": f"Answer {i}"})

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response."
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        with override_settings(RAG_MAX_HISTORY_TURNS=10):
            result = run_rag_query(
                question="Final question?",
                document_id="doc-789",
                conversation_history=history,
            )

        # Assert — the last 20 messages (10 turns) should be included
        assert result["content"] == "Response."
        # Verify the mock was called with the right messages
        call_args = mock_openai.return_value.chat.completions.create.call_args
        assert call_args is not None
        messages = call_args.kwargs["messages"]

        # messages = [system, *history (last 20), user]
        assert len(messages) == 1 + 20 + 1  # system + 20 history + user

        # The last history message should be the 20th assistant answer
        assert messages[-2]["role"] == "assistant"
        assert messages[-2]["content"] == "Answer 19"

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_openai_error_handling(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Mock OpenAI to raise an exception, verify RAGServiceException is raised."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = []
        mock_openai.return_value.chat.completions.create.side_effect = Exception(
            "OpenAI API error"
        )

        # Act / Assert
        with pytest.raises(RAGServiceException, match="OpenAI API call failed"):
            run_rag_query(
                question="Test?",
                document_id="doc-err",
            )

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_embedding_error_handling(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Mock embed_query to raise, verify RAGServiceException."""
        # Arrange
        mock_embed_query.side_effect = Exception("Embedding failed")

        # Act / Assert
        with pytest.raises(RAGServiceException, match="Failed to embed question"):
            run_rag_query(
                question="Test?",
                document_id="doc-err",
            )

        # Ensure OpenAI was never called
        mock_openai.return_value.chat.completions.create.assert_not_called()

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_search_error_handling(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Mock search_chunks to raise, verify RAGServiceException."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.side_effect = Exception("Search failed")

        # Act / Assert
        with pytest.raises(RAGServiceException, match="Failed to search chunks"):
            run_rag_query(
                question="Test?",
                document_id="doc-err",
            )

        # Ensure OpenAI was never called
        mock_openai.return_value.chat.completions.create.assert_not_called()

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_empty_chunks_returns_response(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """No chunks found, still calls OpenAI with empty context."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = []

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I don't have enough information."
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 60
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        result = run_rag_query(
            question="Test?",
            document_id="doc-empty",
        )

        # Assert
        assert result["content"] == "I don't have enough information."
        assert result["sources"] == []
        assert len(result["raw_chunks"]) == 0

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_custom_top_k(
        self,
        mock_openai: MagicMock,
        mock_embed_query: MagicMock,
        mock_search_chunks: MagicMock,
    ) -> None:
        """Passing top_k=3 is forwarded to search_chunks."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = []

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response."
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        run_rag_query(
            question="Test?",
            document_id="doc-topk",
            top_k=3,
        )

        # Assert
        mock_search_chunks.assert_called_once_with(
            document_id="doc-topk",
            query_vector=[0.1] * 768,
            top_k=3,
        )
