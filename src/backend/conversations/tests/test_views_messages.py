"""
Tests for the conversation message view endpoint.

Covers:
- :class:`~conversations.views.ConversationMessageView` (POST /messages/)
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
    return Document.objects.create(
        user=user,
        title=kwargs.get("title", "test-doc.pdf"),
        filename=kwargs.get("filename", "test-doc.pdf"),
        original_filename=kwargs.get("original_filename", "test-doc.pdf"),
        file_path=kwargs.get("file_path", "/storage/test-doc.pdf"),
        file_size=kwargs.get("file_size", 2048),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        processing_status=processing_status,
    )


# ---------------------------------------------------------------------------
# Tests — ConversationMessageView (POST /conversations/<uuid>/messages/)
# ---------------------------------------------------------------------------


class ConversationMessageViewTests(TestCase):
    """Tests for the :class:`ConversationMessageView` endpoint."""

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
            email="msg-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-msg@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conversation",
        )
        self.url = reverse(
            "conversations:conversation-messages",
            kwargs={"conversation_id": self.conversation.id},
        )

    # -- Helper to POST a question ------------------------------------------

    def _post_question(
        self,
        content: str = "What is this document about?",
        **extra,
    ):
        """POST a question to the messages endpoint."""
        payload = {"content": content}
        return self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
            **extra,
        )

    # -- 1. Happy path: creates user + assistant messages -------------------

    @patch("conversations.views.run_rag_query")
    def test_post_creates_user_and_assistant_messages(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST with valid question should create 2 messages (user + assistant)."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        response = self._post_question()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify 2 messages in DB
        messages = Message.objects.filter(conversation=self.conversation).order_by(
            "created_at"
        )
        self.assertEqual(messages.count(), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content, "What is this document about?")
        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[1].content, "Based on the document, the answer is...")
        self.assertEqual(messages[1].sources, self._MOCK_RAG_RESPONSE["sources"])
        self.assertEqual(messages[1].token_usage, self._MOCK_RAG_RESPONSE["token_usage"])

    # -- 2. Response shape matches MessageSerializer ------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_returns_201_with_message_serializer(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST should return response matching MessageSerializer fields."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        response = self._post_question()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["role"], "assistant")
        self.assertEqual(data["content"], "Based on the document, the answer is...")
        self.assertEqual(data["sources"], self._MOCK_RAG_RESPONSE["sources"])
        self.assertEqual(data["token_usage"], self._MOCK_RAG_RESPONSE["token_usage"])
        self.assertIn("created_at", data)

    # -- 3. Conversation updated_at is touched ------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_touches_conversation_updated_at(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST should update conversation.updated_at."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        original_updated_at = self.conversation.updated_at

        response = self._post_question()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.conversation.refresh_from_db()
        self.assertGreater(self.conversation.updated_at, original_updated_at)

    # -- 4. Invalid conversation ID -> 404 ----------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_invalid_conversation_id(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST with random UUID should return 404."""
        url = reverse(
            "conversations:conversation-messages",
            kwargs={"conversation_id": uuid.uuid4()},
        )
        payload = {"content": "Hello?"}
        response = self.client.post(
            url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- 5. Other user's conversation -> 403 ---------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_other_users_conversation(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST as a different user should return 403."""
        payload = {"content": "Hello?"}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.other_user),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    # -- 6. Unauthenticated -> 401 ------------------------------------------

    def test_post_unauthenticated(self) -> None:
        """POST without auth header should return 401."""
        payload = {"content": "Hello?"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- 7. Empty content -> 400 --------------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_empty_content(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST with empty content should return 400."""
        response = self._post_question(content="")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- 8. RAG service failure -> 502 --------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_rag_service_failure(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST when RAG service raises RAGServiceException should return 502."""
        mock_run_rag_query.side_effect = RAGServiceException(
            "OpenAI API call failed: Connection error"
        )

        response = self._post_question()
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"], "rag_error")

    # -- 9. Rate limit error -> 429 -----------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_rate_limit_error(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST when RAG service raises rate limit error should return 429."""
        mock_run_rag_query.side_effect = RAGServiceException(
            "rate limit exceeded: 429 Too Many Requests"
        )

        response = self._post_question()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["error"], "rate_limit_exceeded")
        self.assertEqual(response.data["retry_after"], 60)

    # -- 10. Conversation history includes prior messages --------------------

    @patch("conversations.views.run_rag_query")
    def test_post_conversation_history_includes_prior_messages(
        self,
        mock_run_rag_query,
    ) -> None:
        """POST should pass prior messages in conversation_history to RAG."""
        # Create some prior messages
        Message.objects.create(
            conversation=self.conversation,
            role="user",
            content="Prior question",
        )
        Message.objects.create(
            conversation=self.conversation,
            role="assistant",
            content="Prior answer",
        )

        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        response = self._post_question("New question")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify run_rag_query was called with conversation_history
        # containing prior messages + the new user message
        call_kwargs = mock_run_rag_query.call_args[1]
        history = call_kwargs["conversation_history"]
        self.assertEqual(len(history), 3)  # prior user + prior assistant + new user
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Prior question")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "Prior answer")
        self.assertEqual(history[2]["role"], "user")
        self.assertEqual(history[2]["content"], "New question")

    # -- 11. Integration: full conversation flow ----------------------------

    @patch("conversations.views.run_rag_query")
    def test_full_conversation_flow(
        self,
        mock_run_rag_query,
    ) -> None:
        """Full flow: create conv -> ask -> check messages -> ask again -> verify history."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        # First question
        response1 = self._post_question("First question")
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Verify 2 messages after first ask
        messages_after_first = Message.objects.filter(
            conversation=self.conversation
        ).order_by("created_at")
        self.assertEqual(messages_after_first.count(), 2)
        self.assertEqual(messages_after_first[0].content, "First question")
        self.assertEqual(messages_after_first[1].role, "assistant")

        # Second question
        response2 = self._post_question("Second question")
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

        # Verify 4 messages after second ask
        messages_after_second = Message.objects.filter(
            conversation=self.conversation
        ).order_by("created_at")
        self.assertEqual(messages_after_second.count(), 4)
        self.assertEqual(messages_after_second[2].content, "Second question")
        self.assertEqual(messages_after_second[3].role, "assistant")

        # Verify the second call to run_rag_query included history with
        # all prior messages (first user + first assistant + second user)
        call_kwargs = mock_run_rag_query.call_args[1]
        history = call_kwargs["conversation_history"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["content"], "First question")
        self.assertEqual(history[1]["content"], "Based on the document, the answer is...")
        self.assertEqual(history[2]["content"], "Second question")
