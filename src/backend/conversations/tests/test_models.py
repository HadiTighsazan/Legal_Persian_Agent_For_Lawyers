"""
Tests for the conversations app models.

Covers:
- :class:`~conversations.models.Conversation`
- :class:`~conversations.models.Message`
"""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone as tz_utils

from conversations.models import Conversation, Message
from documents.models import Document
from users.models import User


class ConversationModelTests(TestCase):
    """Tests for :class:`~conversations.models.Conversation` and
    :class:`~conversations.models.Message`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="model-test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="test-doc.pdf",
            filename="test-doc.pdf",
            original_filename="test-doc.pdf",
            file_path="/storage/test-doc.pdf",
            file_size=2048,
            mime_type="application/pdf",
            processing_status="completed",
        )

    # -- 1. Create Conversation ------------------------------------------------

    def test_create_conversation(self) -> None:
        """Create a Conversation with a user + document, verify all fields."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="My Conversation",
        )

        self.assertIsInstance(conversation.id, uuid.UUID)
        self.assertEqual(conversation.user, self.user)
        self.assertEqual(conversation.document, self.document)
        self.assertEqual(conversation.title, "My Conversation")
        self.assertIsNotNone(conversation.created_at)
        self.assertIsNotNone(conversation.updated_at)

    # -- 2. Create Message -----------------------------------------------------

    def test_create_message(self) -> None:
        """Create a Message linked to a conversation, verify fields."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        message = Message.objects.create(
            conversation=conversation,
            role="user",
            content="What is this document about?",
        )

        self.assertIsInstance(message.id, uuid.UUID)
        self.assertEqual(message.conversation, conversation)
        self.assertEqual(message.role, "user")
        self.assertEqual(message.content, "What is this document about?")
        self.assertEqual(message.sources, [])
        self.assertIsNone(message.token_usage)
        self.assertIsNotNone(message.created_at)

    # -- 3. Conversation __str__ -----------------------------------------------

    def test_conversation_str(self) -> None:
        """Verify ``str(conversation)`` returns expected format."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="My Conversation",
        )
        expected = f"Conversation about {self.document.title} ({self.user.email})"
        self.assertEqual(str(conversation), expected)

    # -- 4. Message __str__ ----------------------------------------------------

    def test_message_str(self) -> None:
        """Verify ``str(message)`` returns ``{role}: {content[:50]}...``."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        message = Message.objects.create(
            conversation=conversation,
            role="user",
            content="What is this document about?",
        )
        expected = f"{message.role}: {message.content[:50]}..."
        self.assertEqual(str(message), expected)

    # -- 5. Cascade delete conversation -> messages ----------------------------

    def test_cascade_delete_conversation(self) -> None:
        """Delete a conversation, verify all its messages are also deleted."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        Message.objects.create(conversation=conversation, role="user", content="Hello")
        Message.objects.create(
            conversation=conversation, role="assistant", content="Hi!",
        )

        self.assertEqual(Message.objects.filter(conversation=conversation).count(), 2)

        conversation.delete()

        self.assertEqual(Message.objects.filter(conversation=conversation).count(), 0)
        self.assertFalse(Conversation.objects.filter(id=conversation.id).exists())

    # -- 6. Cascade delete user -> conversations -------------------------------

    def test_cascade_delete_user(self) -> None:
        """Delete a user, verify their conversations are also deleted."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )

        self.user.delete()

        self.assertFalse(Conversation.objects.filter(id=conversation.id).exists())

    # -- 7. Cascade delete document -> conversations ---------------------------

    def test_cascade_delete_document(self) -> None:
        """Delete a document, verify its conversations are also deleted."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )

        self.document.delete()

        self.assertFalse(Conversation.objects.filter(id=conversation.id).exists())

    # -- 8. Message ordering ---------------------------------------------------

    def test_message_ordering(self) -> None:
        """Messages should be ordered by ``created_at`` by default."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )

        # Create messages with explicit timestamps
        earlier = Message.objects.create(
            conversation=conversation,
            role="user",
            content="First",
        )
        later = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Second",
        )

        messages = Message.objects.filter(conversation=conversation)
        self.assertEqual(messages[0].id, earlier.id)
        self.assertEqual(messages[1].id, later.id)

    # -- 9. Conversation updated_at auto_now -----------------------------------

    def test_conversation_updated_at_auto_now(self) -> None:
        """Create conversation, save it again, verify ``updated_at`` changes."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        original_updated_at = conversation.updated_at

        # Wait a tiny bit and save again
        conversation.title = "Updated Title"
        conversation.save()

        self.assertGreater(conversation.updated_at, original_updated_at)

    # -- 10. Message sources JSON field ----------------------------------------

    def test_message_sources_json_field(self) -> None:
        """Create a message with complex ``sources`` data, verify JSON storage."""
        conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Test Conv",
        )
        complex_sources = [
            {
                "chunk_id": str(uuid.uuid4()),
                "page_start": 1,
                "page_end": 3,
                "content_preview": "Some content...",
                "relevance_score": 0.95,
            },
            {
                "chunk_id": str(uuid.uuid4()),
                "page_start": 4,
                "page_end": 6,
                "content_preview": "More content...",
                "relevance_score": 0.88,
            },
        ]

        message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Here is the answer.",
            sources=complex_sources,
            token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

        # Refresh from DB to verify JSON storage
        message.refresh_from_db()
        self.assertEqual(message.sources, complex_sources)
        self.assertEqual(message.token_usage["total_tokens"], 150)
