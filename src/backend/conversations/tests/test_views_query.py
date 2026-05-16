"""
Tests for the document direct query view endpoint.

Covers:
- :class:`~conversations.views.DocumentDirectQueryView` (POST /documents/<uuid>/query/)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conversations.models import Conversation, Message
from conversations.rag_service import RAGServiceException
from documents.models import Document
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header(user: User) -> dict[str, str]:
    """Return an Authorization header dict for the given user.

    Uses ``rest_framework_simplejwt`` to generate a valid access token.
    """
    from rest_framework_simplejwt.tokens import RefreshToken  # noqa: PLC0415

    refresh = RefreshToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


def _create_document(
    user: User,
    processing_status: str = "completed",
    **kwargs,
) -> Document:
    """Create a Document with sensible defaults for testing."""
    # Keep status in sync with processing_status by default.
    status = kwargs.get("status", processing_status if processing_status == "completed" else "uploaded")
    return Document.objects.create(
        user=user,
        title=kwargs.get("title", "test-doc.pdf"),
        filename=kwargs.get("filename", "test-doc.pdf"),
        original_filename=kwargs.get("original_filename", "test-doc.pdf"),
        file_path=kwargs.get("file_path", "/storage/test-doc.pdf"),
        file_size=kwargs.get("file_size", 2048),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        processing_status=processing_status,
        status=status,
    )


# ---------------------------------------------------------------------------
# Tests — DocumentDirectQueryView (POST /documents/<uuid>/query/)
# ---------------------------------------------------------------------------


class DocumentDirectQueryViewTests(TestCase):
    """Tests for the :class:`DocumentDirectQueryView` endpoint."""

    _MOCK_RAG_RESPONSE: dict = {
        "content": "Based on the document, the answer is...",
        "sources": [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 3,
                "content_preview": "Sample content...",
                "relevance_score": 0.95,
            }
        ],
        "token_usage": {
            "prompt_tokens": 350,
            "completion_tokens": 50,
            "total_tokens": 400,
        },
        "raw_chunks": [],
    }

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="query-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-query@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse(
            "documents:document-query",
            kwargs={"document_id": self.document.id},
        )

    def _post_query(
        self,
        question: str = "What is this document about?",
        top_k: int | None = None,
        **extra,
    ):
        """Helper to POST a direct query."""
        payload: dict = {"question": question}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
            **extra,
        )

    # -- 1. Happy path: returns 200 with answer, sources, token_usage ---------

    @patch("conversations.views.run_rag_query")
    def test_post_returns_200_with_answer_sources_token_usage(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST with valid question should return 200 with answer, sources, token_usage."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        response = self._post_query()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("answer", data)
        self.assertEqual(data["answer"], "Based on the document, the answer is...")
        self.assertIn("sources", data)
        self.assertEqual(data["sources"], self._MOCK_RAG_RESPONSE["sources"])
        self.assertIn("token_usage", data)
        self.assertEqual(data["token_usage"], self._MOCK_RAG_RESPONSE["token_usage"])

    # -- 2. Stateless: no Message or Conversation objects created -------------

    @patch("conversations.views.run_rag_query")
    def test_post_does_not_create_any_messages_or_conversations(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST should NOT create any Message or Conversation objects."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        initial_msg_count = Message.objects.count()
        initial_conv_count = Conversation.objects.count()

        response = self._post_query()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify no new records were created
        self.assertEqual(Message.objects.count(), initial_msg_count)
        self.assertEqual(Conversation.objects.count(), initial_conv_count)

    # -- 3. Correct args passed to run_rag_query ------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_calls_run_rag_query_with_correct_args(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST should call run_rag_query with question, document_id, empty history, and top_k."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        self._post_query(question="Test question?", top_k=3)

        mock_run_rag_query.assert_called_once_with(
            question="Test question?",
            document_id=str(self.document.id),
            conversation_history=[],
            top_k=3,
        )

    # -- 4. Document not found -> 404 -----------------------------------------

    def test_post_document_not_found(self) -> None:
        """POST with non-existent document_id should return 404."""
        url = reverse(
            "documents:document-query",
            kwargs={"document_id": uuid.uuid4()},
        )
        payload = {"question": "Hello?"}
        response = self.client.post(
            url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- 5. Other user's document -> 403 --------------------------------------

    def test_post_other_users_document(self) -> None:
        """POST as a different user should return 403."""
        payload = {"question": "Hello?"}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.other_user),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    # -- 6. Unauthenticated -> 401 --------------------------------------------

    def test_post_unauthenticated(self) -> None:
        """POST without auth header should return 401."""
        payload = {"question": "Hello?"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- 7. Document not completed -> 422 -------------------------------------

    def test_post_document_not_completed(self) -> None:
        """POST with a document that has processing_status != 'completed' should return 422."""
        unprocessed_doc = _create_document(self.user, processing_status="pending")
        url = reverse(
            "documents:document-query",
            kwargs={"document_id": unprocessed_doc.id},
        )
        payload = {"question": "Hello?"}
        response = self.client.post(
            url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["error"], "processing_incomplete")

    # -- 8. Empty question -> 400 ---------------------------------------------

    def test_post_empty_question(self) -> None:
        """POST with empty question should return 400."""
        response = self._post_query(question="")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- 9. RAG service failure -> 502 ----------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_rag_service_failure(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST when RAG service raises RAGServiceException should return 502."""
        mock_run_rag_query.side_effect = RAGServiceException(
            "OpenAI API call failed: Connection error"
        )

        response = self._post_query()
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"], "rag_error")

    # -- 10. Rate limit error -> 429 ------------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_rate_limit_error(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST when RAG service raises rate limit error should return 429."""
        mock_run_rag_query.side_effect = RAGServiceException(
            "rate limit exceeded: 429 Too Many Requests"
        )

        response = self._post_query()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["error"], "rate_limit_exceeded")
        self.assertEqual(response.data["retry_after"], 60)

    # -- 11. Default top_k is 15 ----------------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_default_top_k(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST without top_k should default to 15."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        self._post_query(question="Test question?")

        call_kwargs = mock_run_rag_query.call_args[1]
        self.assertEqual(call_kwargs["top_k"], 15)
