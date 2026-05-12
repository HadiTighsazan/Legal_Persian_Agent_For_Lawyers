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
    hub_metadata = serializers.JSONField(
        read_only=True,
        allow_null=True,
        help_text="Metadata for Global RAG queries: per-hub results, sub-queries, "
                  "and hub-level token usage. Null for local RAG queries.",
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
            "hub_metadata",
            "created_at",
        ]


class ConversationListSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~conversations.models.Conversation` for list views.

    Includes ``document_id`` and ``document_title`` sourced from the related
    :class:`~documents.models.Document` (nullable for Global RAG conversations),
    and an annotated ``message_count``.

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
        allow_null=True,
        help_text="UUID of the associated document (null for Global RAG conversations).",
    )
    document_title = serializers.CharField(
        read_only=True,
        source="document.title",
        allow_null=True,
        help_text="Title of the associated document (null for Global RAG conversations).",
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

    ``document_id`` is optional to support Global RAG conversations that are
    not tied to any specific user-uploaded document.

    When ``document_id`` is provided, validates that:
    1. The referenced document exists.
    2. The document belongs to the requesting user.
    3. The document's processing is complete.
    """

    document_id = serializers.UUIDField(
        required=False,
        help_text="UUID of the document to create a conversation about. "
                  "Omit for Global RAG conversations (no document).",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Optional human-readable title for the conversation.",
    )

    def validate_document_id(self, value: uuid.UUID | None) -> Document | None:
        """Validate the document ID if provided.

        If ``value`` is ``None`` (Global RAG conversation), skip validation
        and return ``None``. Otherwise, validate that the document exists,
        belongs to the user, and is fully processed.

        Args:
            value: The UUID of the document, or ``None``.

        Returns:
            The validated :class:`~documents.models.Document` instance,
            or ``None`` if no document was provided.

        Raises:
            serializers.ValidationError: If the document does not exist,
                does not belong to the user, or is not fully processed.
        """
        if value is None:
            return None

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

    MODE_CHOICES = [
        ("local_rag", "Local RAG — search within the conversation's document"),
        ("global_rag", "Global RAG — search across all legal knowledge hubs"),
    ]

    content = serializers.CharField(
        required=True,
        min_length=1,
        max_length=10000,
        help_text="The question text to ask (1–10,000 characters).",
    )
    mode = serializers.ChoiceField(
        choices=MODE_CHOICES,
        default="local_rag",
        required=False,
        help_text="RAG mode: 'local_rag' (default) searches within the "
                  "conversation's document; 'global_rag' searches across all "
                  "legal knowledge hubs (legislation, judicial precedent, "
                  "advisory opinions).",
    )

    def validate_content(self, value: str) -> str:
        """Normalize Arabic character variants to Persian equivalents.

        Converts Arabic Yeh (U+064A) → Persian Yeh (U+06CC) and
        Arabic Kaf (U+0643) → Persian Kaf (U+06A9) at the input
        validation layer, providing defense-in-depth against LLM
        failures caused by mixed Unicode codepoints.
        """
        _ARABIC_TO_PERSIAN = str.maketrans({
            '\u064A': '\u06CC',  # Arabic Yeh → Persian Yeh
            '\u0643': '\u06A9',  # Arabic Kaf → Persian Kaf
        })
        return value.translate(_ARABIC_TO_PERSIAN)


class DirectQuerySerializer(serializers.Serializer):
    """Validate input for querying a document directly (POST /documents/{document_id}/query)."""

    question = serializers.CharField(
        required=True,
        min_length=1,
        help_text="The question text to ask (minimum 1 character).",
    )
    top_k = serializers.IntegerField(
        required=False,
        default=15,
        min_value=1,
        max_value=20,
        help_text="Number of top chunks to retrieve (1–20, default 15).",
    )
