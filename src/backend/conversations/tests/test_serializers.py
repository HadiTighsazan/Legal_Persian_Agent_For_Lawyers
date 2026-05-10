"""
Tests for the conversations app serializers.

Covers:
- :class:`~conversations.serializers.MessageSerializer`
- :class:`~conversations.serializers.ConversationListSerializer`
- :class:`~conversations.serializers.ConversationDetailSerializer`
- :class:`~conversations.serializers.ConversationCreateSerializer`
- :class:`~conversations.serializers.AskQuestionSerializer`
- :class:`~conversations.serializers.DirectQuerySerializer`
"""

from __future__ import annotations

import uuid

from django.db.models import Count
from django.test import TestCase
from django.utils import timezone as tz_utils

from conversations.models import Conversation, Message
from conversations.serializers import (
    AskQuestionSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    DirectQuerySerializer,
    MessageSerializer,
)
from documents.models import Document
from users.models import User


# ---------------------------------------------------------------------------
# Tests — MessageSerializer
# ---------------------------------------------------------------------------


class MessageSerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.MessageSerializer`."""

    def setUp(self) -> None:
        self.now = tz_utils.now()
        self.data = {
            "id": uuid.uuid4(),
            "role": "user",
            "content": "What is this document about?",
            "sources": [
                {"chunk_id": str(uuid.uuid4()), "content": "Some source text"}
            ],
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 100},
            "created_at": self.now,
        }

    def test_valid_data_passes(self) -> None:
        """All fields present should pass validation."""
        serializer = MessageSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_read_only_fields(self) -> None:
        """``id``, ``created_at``, ``sources``, ``token_usage``, and ``hub_metadata`` should be read_only."""
        serializer = MessageSerializer()
        for field_name in ("id", "created_at", "sources", "token_usage", "hub_metadata"):
            with self.subTest(field=field_name):
                self.assertTrue(
                    serializer.fields[field_name].read_only,
                    f"Field '{field_name}' should be read_only",
                )

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output dict with correct types."""
        serializer = MessageSerializer(instance=self.data)
        output = serializer.data
        # UUID → str
        self.assertEqual(output["id"], str(self.data["id"]))
        self.assertEqual(output["role"], "user")
        self.assertEqual(output["content"], "What is this document about?")
        # datetime → str
        self.assertIsInstance(output["created_at"], str)
        # JSONField
        self.assertEqual(output["sources"], self.data["sources"])
        self.assertEqual(output["token_usage"], self.data["token_usage"])

    def test_hub_metadata_in_output(self) -> None:
        """``hub_metadata`` should be included in serialized output when present."""
        hub_metadata = {
            "legislation": {
                "chunks_count": 2,
                "sub_query": {"fts_query": "test", "vector_query": "test"},
            },
        }
        data_with_hub = {**self.data, "hub_metadata": hub_metadata}
        serializer = MessageSerializer(instance=data_with_hub)
        output = serializer.data
        self.assertIn("hub_metadata", output)
        self.assertEqual(output["hub_metadata"], hub_metadata)

    def test_hub_metadata_allows_null(self) -> None:
        """``hub_metadata`` should allow null (for local_rag messages)."""
        data_null_hub = {**self.data, "hub_metadata": None}
        serializer = MessageSerializer(instance=data_null_hub)
        output = serializer.data
        self.assertIn("hub_metadata", output)
        self.assertIsNone(output["hub_metadata"])

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = MessageSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ConversationListSerializer
# ---------------------------------------------------------------------------


class ConversationListSerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.ConversationListSerializer`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="test@example.com",
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
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="My Conversation",
        )
        # Create some messages so message_count > 0
        Message.objects.create(
            conversation=self.conversation,
            role="user",
            content="Hello",
        )
        Message.objects.create(
            conversation=self.conversation,
            role="assistant",
            content="Hi there!",
        )

    def _get_annotated_conversation(self) -> Conversation:
        """Return the conversation annotated with ``message_count``.

        The view is expected to annotate the queryset with
        ``Count('messages')`` to avoid N+1 queries.
        """
        return Conversation.objects.annotate(
            message_count=Count("messages"),
        ).get(pk=self.conversation.pk)

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output dict with correct types."""
        conv = self._get_annotated_conversation()
        serializer = ConversationListSerializer(instance=conv)
        output = serializer.data
        # UUID → str
        self.assertEqual(output["id"], str(self.conversation.id))
        self.assertEqual(output["document_id"], str(self.document.id))
        self.assertEqual(output["document_title"], "test-doc.pdf")
        self.assertEqual(output["title"], "My Conversation")
        self.assertEqual(output["message_count"], 2)
        # datetime → str
        self.assertIsInstance(output["created_at"], str)
        self.assertIsInstance(output["updated_at"], str)

    def test_document_title_from_source(self) -> None:
        """``document_title`` should come from the related document."""
        conv = self._get_annotated_conversation()
        serializer = ConversationListSerializer(instance=conv)
        output = serializer.data
        self.assertEqual(output["document_title"], self.document.title)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = ConversationListSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ConversationDetailSerializer
# ---------------------------------------------------------------------------


class ConversationDetailSerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.ConversationDetailSerializer`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="test@example.com",
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
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="My Conversation",
        )
        self.msg1 = Message.objects.create(
            conversation=self.conversation,
            role="user",
            content="Hello",
        )
        self.msg2 = Message.objects.create(
            conversation=self.conversation,
            role="assistant",
            content="Hi there!",
            sources=[{"chunk_id": str(uuid.uuid4())}],
            token_usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    def _get_annotated_conversation(self) -> Conversation:
        """Return the conversation annotated with ``message_count``."""
        return Conversation.objects.annotate(
            message_count=Count("messages"),
        ).get(pk=self.conversation.pk)

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output with nested messages."""
        conv = self._get_annotated_conversation()
        serializer = ConversationDetailSerializer(instance=conv)
        output = serializer.data
        self.assertEqual(output["id"], str(self.conversation.id))
        self.assertEqual(output["document_title"], "test-doc.pdf")
        self.assertEqual(output["message_count"], 2)
        # Nested messages
        self.assertEqual(len(output["messages"]), 2)
        self.assertEqual(output["messages"][0]["role"], "user")
        self.assertEqual(output["messages"][0]["content"], "Hello")
        self.assertEqual(output["messages"][1]["role"], "assistant")
        self.assertEqual(output["messages"][1]["content"], "Hi there!")
        # UUID → str in nested messages
        self.assertIsInstance(output["messages"][0]["id"], str)
        self.assertIsInstance(output["messages"][0]["created_at"], str)

    def test_empty_messages_list(self) -> None:
        """A conversation with no messages should still serialize correctly."""
        empty_conv = Conversation.objects.annotate(
            message_count=Count("messages"),
        ).get(pk=Conversation.objects.create(
            user=self.user,
            document=self.document,
            title="Empty Conversation",
        ).pk)
        serializer = ConversationDetailSerializer(instance=empty_conv)
        output = serializer.data
        self.assertEqual(output["messages"], [])
        self.assertEqual(output["message_count"], 0)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = ConversationDetailSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ConversationCreateSerializer
# ---------------------------------------------------------------------------


class ConversationCreateSerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.ConversationCreateSerializer`.

    Requires DB access — uses ``django.test.TestCase`` to create actual
    ``User`` and ``Document`` instances.
    """

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="otherpass123",
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
        self.unprocessed_document = Document.objects.create(
            user=self.user,
            title="pending-doc.pdf",
            filename="pending-doc.pdf",
            original_filename="pending-doc.pdf",
            file_path="/storage/pending-doc.pdf",
            file_size=1024,
            mime_type="application/pdf",
            processing_status="pending",
        )

    def _get_serializer(
        self,
        data: dict,
        user: User | None = None,
    ) -> ConversationCreateSerializer:
        """Helper to create a serializer with a mock request context."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post("/conversations/")
        request.user = user or self.user
        return ConversationCreateSerializer(data=data, context={"request": request})

    def test_valid_data_passes(self) -> None:
        """Valid ``document_id`` and ``title`` should pass validation."""
        serializer = self._get_serializer(
            {"document_id": self.document.id, "title": "My Conversation"},
        )
        self.assertTrue(serializer.is_valid())

    def test_valid_data_without_title(self) -> None:
        """Valid ``document_id`` without ``title`` should pass validation."""
        serializer = self._get_serializer(
            {"document_id": self.document.id},
        )
        self.assertTrue(serializer.is_valid())

    def test_non_existent_document(self) -> None:
        """A random UUID should raise a ``ValidationError``."""
        serializer = self._get_serializer(
            {"document_id": uuid.uuid4()},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("document_id", serializer.errors)
        self.assertIn(
            "Document does not exist",
            str(serializer.errors["document_id"]),
        )

    def test_wrong_owner_document(self) -> None:
        """A document owned by a different user should raise a ``ValidationError``."""
        serializer = self._get_serializer(
            {"document_id": self.document.id},
            user=self.other_user,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("document_id", serializer.errors)
        self.assertIn(
            "Document does not belong to you",
            str(serializer.errors["document_id"]),
        )

    def test_unprocessed_document(self) -> None:
        """A document with ``processing_status='pending'`` should raise a ``ValidationError``."""
        serializer = self._get_serializer(
            {"document_id": self.unprocessed_document.id},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("document_id", serializer.errors)
        self.assertIn(
            "Document processing is not complete",
            str(serializer.errors["document_id"]),
        )

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = ConversationCreateSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — AskQuestionSerializer
# ---------------------------------------------------------------------------


class AskQuestionSerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.AskQuestionSerializer`."""

    def test_valid_content_passes(self) -> None:
        """A valid content string should pass validation."""
        serializer = AskQuestionSerializer(data={"content": "What is this about?"})
        self.assertTrue(serializer.is_valid())

    def test_empty_content_fails(self) -> None:
        """An empty string should fail validation (``min_length=1``)."""
        serializer = AskQuestionSerializer(data={"content": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("content", serializer.errors)

    def test_content_too_long(self) -> None:
        """A string longer than 10,000 characters should fail validation."""
        long_content = "a" * 10001
        serializer = AskQuestionSerializer(data={"content": long_content})
        self.assertFalse(serializer.is_valid())
        self.assertIn("content", serializer.errors)

    def test_missing_content_fails(self) -> None:
        """Omitting ``content`` should fail validation."""
        serializer = AskQuestionSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("content", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = AskQuestionSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )

    # -- Mode field tests (Phase 2a — Global RAG) ---------------------------

    def test_default_mode_is_local_rag(self) -> None:
        """Omitting ``mode`` should default to ``'local_rag'``."""
        serializer = AskQuestionSerializer(data={"content": "Test question"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["mode"], "local_rag")

    def test_valid_global_rag_mode(self) -> None:
        """``mode='global_rag'`` should pass validation."""
        serializer = AskQuestionSerializer(
            data={"content": "Test question", "mode": "global_rag"},
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["mode"], "global_rag")

    def test_valid_local_rag_mode(self) -> None:
        """``mode='local_rag'`` should pass validation."""
        serializer = AskQuestionSerializer(
            data={"content": "Test question", "mode": "local_rag"},
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["mode"], "local_rag")

    def test_invalid_mode_fails(self) -> None:
        """An invalid ``mode`` value should fail validation."""
        serializer = AskQuestionSerializer(
            data={"content": "Test question", "mode": "invalid_mode"},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("mode", serializer.errors)


# ---------------------------------------------------------------------------
# Tests — DirectQuerySerializer
# ---------------------------------------------------------------------------


class DirectQuerySerializerTests(TestCase):
    """Validate :class:`~conversations.serializers.DirectQuerySerializer`."""

    def test_valid_data_passes(self) -> None:
        """A valid ``question`` and ``top_k`` should pass validation."""
        serializer = DirectQuerySerializer(
            data={"question": "What is this?", "top_k": 10},
        )
        self.assertTrue(serializer.is_valid())

    def test_default_top_k(self) -> None:
        """Omitting ``top_k`` should default to 5."""
        serializer = DirectQuerySerializer(data={"question": "What is this?"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["top_k"], 5)

    def test_top_k_min_value(self) -> None:
        """``top_k=0`` should fail validation (``min_value=1``)."""
        serializer = DirectQuerySerializer(
            data={"question": "What is this?", "top_k": 0},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("top_k", serializer.errors)

    def test_top_k_max_value(self) -> None:
        """``top_k=21`` should fail validation (``max_value=20``)."""
        serializer = DirectQuerySerializer(
            data={"question": "What is this?", "top_k": 21},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("top_k", serializer.errors)

    def test_empty_question_fails(self) -> None:
        """An empty ``question`` should fail validation (``min_length=1``)."""
        serializer = DirectQuerySerializer(data={"question": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("question", serializer.errors)

    def test_missing_question_fails(self) -> None:
        """Omitting ``question`` should fail validation."""
        serializer = DirectQuerySerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("question", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = DirectQuerySerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )
