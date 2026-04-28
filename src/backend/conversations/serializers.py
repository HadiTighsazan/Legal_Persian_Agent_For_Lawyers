"""
Serializers for the conversations app.

Provides serializers for :class:`~conversations.models.Conversation` and
:class:`~conversations.models.Message` models, including input validation
for creating conversations, asking questions, and direct document queries.
"""

from __future__ import annotations

import uuid

from rest_framework import serializers

from conversations.models import Conversation, Message
from documents.models import Document


class MessageSerializer(serializers.ModelSerializer):
    """Serialize a single :class:`~conversations.models.Message` instance.

    ``sources`` and ``token_usage`` are read-only because they are set
    programmatically by the RAG pipeline, not by user input.
    """

    id = serializers.UUIDField(
        read_only=True,
        help_text="Unique identifier of the message.",
    )
    role = serializers.CharField(
        help_text="Role of the message sender (user, assistant, or system).",
    )
    content = serializers.CharField(
        help_text="Text content of the message.",
    )
    sources = serializers.JSONField(
        read_only=True,
        help_text="List of source chunks used to generate the response.",
    )
    token_usage = serializers.JSONField(
        read_only=True,
        allow_null=True,
        help_text="Token usage statistics for the message, or null if not available.",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the message was created.",
    )

    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "sources",
            "token_usage",
            "created_at",
        ]


class ConversationListSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~conversations.models.Conversation` for list views.

    Includes ``document_id`` and ``document_title`` sourced from the related
    :class:`~documents.models.Document`, and an annotated ``message_count``.

    .. note::

       ``message_count`` is an ``IntegerField(read_only=True)``. The view is
       responsible for annotating the queryset with
       ``Count('messages', distinct=True)`` to avoid N+1 queries.
    """

    id = serializers.UUIDField(
        read_only=True,
        help_text="Unique identifier of the conversation.",
    )
    document_id = serializers.UUIDField(
        read_only=True,
        source="document.id",
        help_text="UUID of the associated document.",
    )
    document_title = serializers.CharField(
        read_only=True,
        source="document.title",
        help_text="Title of the associated document.",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Human-readable title for the conversation.",
    )
    message_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of messages in the conversation (annotated by the view).",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the conversation was created.",
    )
    updated_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the conversation was last updated.",
    )

    class Meta:
        model = Conversation
        fields = [
            "id",
            "document_id",
            "document_title",
            "title",
            "message_count",
            "created_at",
            "updated_at",
        ]


class ConversationDetailSerializer(ConversationListSerializer):
    """Serialize a :class:`~conversations.models.Conversation` with nested messages.

    Inherits all fields from :class:`ConversationListSerializer` and adds
    a ``messages`` list.
    """

    messages = MessageSerializer(
        many=True,
        read_only=True,
        help_text="List of messages in the conversation.",
    )

    class Meta(ConversationListSerializer.Meta):
        fields = ConversationListSerializer.Meta.fields + ["messages"]


class ConversationCreateSerializer(serializers.Serializer):
    """Validate input for creating a new conversation (POST /conversations).

    Validates that:
    1. The referenced document exists.
    2. The document belongs to the requesting user.
    3. The document's processing is complete.
    """

    document_id = serializers.UUIDField(
        required=True,
        help_text="UUID of the document to create a conversation about.",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Optional human-readable title for the conversation.",
    )

    def validate_document_id(self, value: uuid.UUID) -> Document:
        """Validate that the document exists, belongs to the user, and is processed.

        Extracts the authenticated user from ``self.context['request'].user``
        to verify document ownership.

        Args:
            value: The UUID of the document to validate.

        Returns:
            The validated :class:`~documents.models.Document` instance.

        Raises:
            serializers.ValidationError: If the document does not exist,
                does not belong to the user, or is not fully processed.
        """
        request = self.context.get("request")
        if request is None:
            raise serializers.ValidationError("Request context is required.")

        try:
            document = Document.objects.get(id=value)
        except Document.DoesNotExist:
            raise serializers.ValidationError("Document does not exist.")

        if document.user != request.user:
            raise serializers.ValidationError("Document does not belong to you.")

        if document.processing_status != "completed":
            raise serializers.ValidationError("Document processing is not complete.")

        return document


class AskQuestionSerializer(serializers.Serializer):
    """Validate input for asking a question in a conversation (POST /conversations/{id}/messages)."""

    content = serializers.CharField(
        required=True,
        min_length=1,
        max_length=10000,
        help_text="The question text to ask (1–10,000 characters).",
    )


class DirectQuerySerializer(serializers.Serializer):
    """Validate input for querying a document directly (POST /documents/{document_id}/query)."""

    question = serializers.CharField(
        required=True,
        min_length=1,
        help_text="The question text to ask (minimum 1 character).",
    )
    top_k = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=20,
        help_text="Number of top chunks to retrieve (1–20, default 5).",
    )
