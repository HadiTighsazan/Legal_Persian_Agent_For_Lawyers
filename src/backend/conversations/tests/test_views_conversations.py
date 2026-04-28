"""
Tests for the conversation CRUD view endpoints.

Covers:
- :class:`~conversations.views.ConversationListCreateView` (POST + GET)
- :class:`~conversations.views.ConversationDetailView` (GET + DELETE)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conversations.models import Conversation, Message
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
