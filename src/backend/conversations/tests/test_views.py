"""
Tests for the conversation API views.

Covers:
- :class:`~conversations.views.ConversationListCreateView` (POST + GET)
- :class:`~conversations.views.ConversationDetailView` (GET + DELETE)
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
# Tests — ConversationListCreateView (POST + GET /conversations/)
# ---------------------------------------------------------------------------


class ConversationListCreateViewTests(TestCase):
    """Tests for the :class:`ConversationListCreateView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse("conversations:conversation-list-create")

    # -- POST: 201 Created (happy path) ------------------------------------

    def test_post_creates_conversation(self) -> None:
        """POST with valid document_id and title should return 201."""
        payload = {
            "document_id": str(self.document.id),
            "title": "My Conversation",
        }
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["document_id"], str(self.document.id))
        self.assertEqual(data["title"], "My Conversation")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertEqual(data["messages"], [])

        # Verify it was actually created in the DB
        self.assertTrue(Conversation.objects.filter(id=data["id"]).exists())

    def test_post_without_title(self) -> None:
        """POST with only document_id should return 201 with empty title."""
        payload = {"document_id": str(self.document.id)}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        # The model has null=True, blank=True for title, so it could be null or ""
        self.assertIn("title", data)

    # -- POST: 401 Unauthenticated -----------------------------------------

    def test_post_unauthenticated(self) -> None:
        """POST without auth header should return 401."""
        payload = {"document_id": str(self.document.id)}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- POST: Validation errors (serializer) ------------------------------

    def test_post_nonexistent_document(self) -> None:
        """POST with a non-existent document_id should return 400."""
        payload = {"document_id": str(uuid.uuid4())}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Document does not exist", str(response.data))

    def test_post_other_users_document(self) -> None:
        """POST with a document owned by another user should return 400."""
        other_doc = _create_document(self.other_user)
        payload = {"document_id": str(other_doc.id)}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Document does not belong to you", str(response.data))

    def test_post_unprocessed_document(self) -> None:
        """POST with a document that has processing_status='pending' should return 400."""
        unprocessed_doc = _create_document(self.user, processing_status="pending")
        payload = {"document_id": str(unprocessed_doc.id)}
        response = self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Document processing is not complete", str(response.data))

    # -- GET: 200 OK (happy path) ------------------------------------------

    def test_get_lists_user_conversations(self) -> None:
        """GET should return only the current user's conversations."""
        # Create conversations for the main user
        Conversation.objects.create(user=self.user, document=self.document, title="Conv 1")
        Conversation.objects.create(user=self.user, document=self.document, title="Conv 2")
        # Create a conversation for another user (should not appear)
        other_doc = _create_document(self.other_user)
        Conversation.objects.create(user=self.other_user, document=other_doc, title="Other Conv")

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)
        titles = [item["title"] for item in data["results"]]
        self.assertIn("Conv 1", titles)
        self.assertIn("Conv 2", titles)
        self.assertNotIn("Other Conv", titles)

    def test_get_with_message_count(self) -> None:
        """GET should include message_count in each result."""
        conv = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        Message.objects.create(conversation=conv, role="user", content="Hello")
        Message.objects.create(conversation=conv, role="assistant", content="Hi!")

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["message_count"], 2)

    # -- GET: Pagination ---------------------------------------------------

    def test_get_pagination_defaults(self) -> None:
        """GET with no pagination params should default to page=1, page_size=20."""
        for i in range(5):
            Conversation.objects.create(
                user=self.user,
                document=self.document,
                title=f"Conv {i}",
            )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 5)
        self.assertEqual(len(data["results"]), 5)

    def test_get_pagination_custom(self) -> None:
        """GET with ?page=1&page_size=2 should return 2 results with next/previous."""
        for i in range(5):
            Conversation.objects.create(
                user=self.user,
                document=self.document,
                title=f"Conv {i}",
            )

        response = self.client.get(
            self.url,
            {"page": 1, "page_size": 2},
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 5)
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["next"], 2)
        self.assertIsNone(data["previous"])

    def test_get_pagination_max_page_size(self) -> None:
        """GET with page_size=200 should be capped at 100."""
        for i in range(150):
            Conversation.objects.create(
                user=self.user,
                document=self.document,
                title=f"Conv {i}",
            )

        response = self.client.get(
            self.url,
            {"page_size": 200},
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 150)
        # Should be capped at 100
        self.assertEqual(len(data["results"]), 100)

    # -- GET: Filter by document_id ----------------------------------------

    def test_get_filter_by_document_id(self) -> None:
        """GET with ?document_id=uuid should filter conversations by document."""
        doc2 = _create_document(self.user, title="second-doc.pdf")
        Conversation.objects.create(user=self.user, document=self.document, title="Conv about doc1")
        Conversation.objects.create(user=self.user, document=doc2, title="Conv about doc2")

        response = self.client.get(
            self.url,
            {"document_id": str(self.document.id)},
            **_auth_header(self.user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "Conv about doc1")

    # -- GET: 401 Unauthenticated ------------------------------------------

    def test_get_unauthenticated(self) -> None:
        """GET without auth header should return 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests — ConversationDetailView (GET + DELETE /conversations/<uuid>/)
# ---------------------------------------------------------------------------


class ConversationDetailViewTests(TestCase):
    """Tests for the :class:`ConversationDetailView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="detail-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-detail@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="My Conversation",
        )
        # Create some messages for detail view tests
        self.msg1 = Message.objects.create(
            conversation=self.conversation,
            role="user",
            content="Hello",
        )
        self.msg2 = Message.objects.create(
            conversation=self.conversation,
            role="assistant",
            content="Hi there!",
        )
        self.url = reverse(
            "conversations:conversation-detail",
            kwargs={"conversation_id": self.conversation.id},
        )

    # -- GET: 200 OK (happy path) ------------------------------------------

    def test_get_returns_conversation_with_messages(self) -> None:
        """GET should return the conversation with nested messages."""
        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(self.conversation.id))
        self.assertEqual(data["document_id"], str(self.document.id))
        self.assertEqual(data["title"], "My Conversation")
        self.assertIn("document_title", data)
        self.assertIn("message_count", data)
        self.assertIn("messages", data)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["role"], "user")
        self.assertEqual(data["messages"][0]["content"], "Hello")
        self.assertEqual(data["messages"][1]["role"], "assistant")
        self.assertEqual(data["messages"][1]["content"], "Hi there!")

    # -- GET: 403 Forbidden -------------------------------------------------

    def test_get_other_users_conversation(self) -> None:
        """GET as a different user should return 403."""
        response = self.client.get(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    # -- GET: 404 Not Found -------------------------------------------------

    def test_get_nonexistent_conversation(self) -> None:
        """GET with a random UUID should return 404."""
        url = reverse(
            "conversations:conversation-detail",
            kwargs={"conversation_id": uuid.uuid4()},
        )
        response = self.client.get(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- GET: 401 Unauthenticated ------------------------------------------

    def test_get_unauthenticated(self) -> None:
        """GET without auth header should return 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- DELETE: 204 No Content (happy path) --------------------------------

    def test_delete_removes_conversation(self) -> None:
        """DELETE should return 204 and remove the conversation from DB."""
        response = self.client.delete(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            Conversation.objects.filter(id=self.conversation.id).exists()
        )

    # -- DELETE: 403 Forbidden ----------------------------------------------

    def test_delete_other_users_conversation(self) -> None:
        """DELETE as a different user should return 403."""
        response = self.client.delete(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")
        # Verify conversation still exists
        self.assertTrue(
            Conversation.objects.filter(id=self.conversation.id).exists()
        )

    # -- DELETE: 404 Not Found ----------------------------------------------

    def test_delete_nonexistent_conversation(self) -> None:
        """DELETE with a random UUID should return 404."""
        url = reverse(
            "conversations:conversation-detail",
            kwargs={"conversation_id": uuid.uuid4()},
        )
        response = self.client.delete(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- DELETE: 401 Unauthenticated ---------------------------------------

    def test_delete_unauthenticated(self) -> None:
        """DELETE without auth header should return 401."""
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


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
    ) -> Response:
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
    ) -> None:
        """POST with empty content should return 400."""
        response = self._post_question(content="")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- 8. RAG service failure -> 502 --------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_rag_service_failure(
        self,
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
    ) -> Response:
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
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
        mock_run_rag_query: patch,
    ) -> None:
        """POST when RAG service raises rate limit error should return 429."""
        mock_run_rag_query.side_effect = RAGServiceException(
            "rate limit exceeded: 429 Too Many Requests"
        )

        response = self._post_query()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["error"], "rate_limit_exceeded")
        self.assertEqual(response.data["retry_after"], 60)

    # -- 11. Default top_k is 5 -----------------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_post_default_top_k(
        self,
        mock_run_rag_query: patch,
    ) -> None:
        """POST without top_k should default to 5."""
        mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

        self._post_query(question="Test question?")

        call_kwargs = mock_run_rag_query.call_args[1]
        self.assertEqual(call_kwargs["top_k"], 5)
