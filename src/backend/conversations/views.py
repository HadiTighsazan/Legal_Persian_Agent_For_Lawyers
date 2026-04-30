"""
Views for the conversations app.

Provides ``ConversationListCreateView`` (POST + GET /conversations/),
``ConversationDetailView`` (GET + DELETE /conversations/{conversation_id}),
and ``ConversationMessageView`` (POST /conversations/{conversation_id}/messages/)
for CRUD operations on conversations and asking questions (Epic E-07, Tasks 4 & 5).
"""

from __future__ import annotations

import logging

from django.db.models import Count
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.models import Conversation, Message
from documents.models import Document
from conversations.rag_service import RAGServiceException, run_rag_query
from conversations.serializers import (
    AskQuestionSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    DirectQuerySerializer,
    MessageSerializer,
)
from providers.base import RateLimitError

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Pagination
# ------------------------------------------------------------------

class ConversationPagination(PageNumberPagination):
    """Pagination for conversation list views."""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_conversation_or_error(
    conversation_id: str,
    request: Request,
) -> tuple[Conversation | None, Response | None]:
    """Fetch a conversation and verify ownership.

    Returns a ``(conversation, None)`` tuple on success, or
    ``(None, error_response)`` on failure.
    """
    try:
        conversation = Conversation.objects.get(id=conversation_id)
    except Conversation.DoesNotExist:
        return None, Response(
            {"error": "not_found", "message": "Conversation not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if conversation.user != request.user:
        return None, Response(
            {
                "error": "permission_denied",
                "message": "You do not have permission to access this conversation.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    return conversation, None


class ConversationListCreateView(APIView):
    """Create or list conversations.

    **Endpoint:** ``POST /conversations/`` and ``GET /conversations/``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **POST Responses:**
        - ``201 Created`` — Conversation created successfully.
        - ``400 Bad Request`` — Validation error (invalid document_id, etc.).
        - ``401 Unauthorized`` — Missing or invalid authentication.

    **GET Responses:**
        - ``200 OK`` — List of conversations returned successfully.
        - ``401 Unauthorized`` — Missing or invalid authentication.
    """

    permission_classes = [IsAuthenticated]

    # ------------------------------------------------------------------
    # POST — Create a new conversation
    # ------------------------------------------------------------------

    def post(self, request: Request) -> Response:
        """Handle the conversation creation POST request."""
        serializer = ConversationCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        document = validated_data["document_id"]  # Document instance
        title = validated_data.get("title", "")

        conversation = Conversation.objects.create(
            user=request.user,
            document=document,
            title=title,
        )

        logger.info(
            "Conversation %s created for user=%s, document=%s",
            conversation.id,
            request.user,
            document.id,
        )

        response_serializer = ConversationDetailSerializer(conversation)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------
    # GET — List conversations for the authenticated user
    # ------------------------------------------------------------------

    def get(self, request: Request) -> Response:
        """Handle the conversation list GET request."""
        # Base queryset: only the current user's conversations
        queryset = Conversation.objects.filter(user=request.user)

        # Optional filter by document_id
        document_id = request.query_params.get("document_id")
        if document_id:
            queryset = queryset.filter(document_id=document_id)

        # Annotate with message count and order by most recent
        queryset = queryset.annotate(
            message_count=Count("messages", distinct=True),
        ).order_by("-updated_at")

        # Pagination using DRF's PageNumberPagination
        paginator = ConversationPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ConversationListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ConversationDetailView(APIView):
    """Retrieve or delete a conversation.

    **Endpoint:** ``GET /conversations/{conversation_id}/`` and
    ``DELETE /conversations/{conversation_id}/``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **GET Responses:**
        - ``200 OK`` — Conversation returned successfully.
        - ``403 Forbidden`` — Conversation belongs to another user.
        - ``404 Not Found`` — Conversation does not exist.
        - ``401 Unauthorized`` — Missing or invalid authentication.

    **DELETE Responses:**
        - ``204 No Content`` — Conversation deleted successfully.
        - ``403 Forbidden`` — Conversation belongs to another user.
        - ``404 Not Found`` — Conversation does not exist.
        - ``401 Unauthorized`` — Missing or invalid authentication.
    """

    permission_classes = [IsAuthenticated]

    # ------------------------------------------------------------------
    # GET — Retrieve a single conversation with messages
    # ------------------------------------------------------------------

    def get(self, request: Request, conversation_id: str) -> Response:
        """Handle the conversation detail GET request."""
        try:
            conversation = Conversation.objects.prefetch_related("messages").annotate(
                message_count=Count("messages"),
            ).get(id=conversation_id)
        except Conversation.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Conversation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if conversation.user != request.user:
            return Response(
                {
                    "error": "permission_denied",
                    "message": "You do not have permission to access this conversation.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ConversationDetailSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # DELETE — Delete a conversation
    # ------------------------------------------------------------------

    def delete(self, request: Request, conversation_id: str) -> Response:
        """Handle the conversation deletion DELETE request."""
        conversation, error = _get_conversation_or_error(
            conversation_id,
            request,
        )
        if error:
            return error

        conversation.delete()

        logger.info(
            "Conversation %s deleted by user=%s",
            conversation_id,
            request.user,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # DELETE — Delete a conversation
    # ------------------------------------------------------------------



class ConversationMessageView(APIView):
    """Handle asking a question in a conversation.

    **Endpoint:** ``POST /conversations/{conversation_id}/messages/``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **POST Responses:**
        - ``201 Created`` — Assistant response created successfully.
        - ``400 Bad Request`` — Validation error (empty content, etc.).
        - ``401 Unauthorized`` — Missing or invalid authentication.
        - ``403 Forbidden`` — Conversation belongs to another user.
        - ``404 Not Found`` — Conversation does not exist.
        - ``429 Too Many Requests`` — OpenAI API rate limit exceeded.
        - ``502 Bad Gateway`` — RAG service error.
    """

    permission_classes = [IsAuthenticated]

    # ------------------------------------------------------------------
    # POST — Ask a question in the conversation
    # ------------------------------------------------------------------

    def post(self, request: Request, conversation_id: str) -> Response:
        """Handle the question-asking POST request."""
        # ------------------------------------------------------------------
        # 1. Fetch conversation + ownership check
        # ------------------------------------------------------------------
        conversation, error = _get_conversation_or_error(conversation_id, request)
        if error:
            return error

        # ------------------------------------------------------------------
        # 2. Validate input with AskQuestionSerializer
        # ------------------------------------------------------------------
        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        question = validated_data["content"]

        # ------------------------------------------------------------------
        # 3. Persist the user message first
        # ------------------------------------------------------------------
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=question,
        )

        # ------------------------------------------------------------------
        # 4. Build conversation history (includes the just-created user msg)
        # ------------------------------------------------------------------
        all_messages = conversation.messages.all().order_by("created_at")
        conversation_history = [
            {"role": msg.role, "content": msg.content}
            for msg in all_messages
        ]

        # ------------------------------------------------------------------
        # 5. Call run_rag_query
        # ------------------------------------------------------------------
        try:
            result = run_rag_query(
                question=question,
                document_id=str(conversation.document_id),
                conversation_history=conversation_history,
                top_k=5,
            )
        except RAGServiceException as e:
            error_msg = str(e).lower()
            if isinstance(e.__cause__, RateLimitError) or "rate limit" in error_msg or "429" in error_msg:
                return Response(
                    {
                        "error": "rate_limit_exceeded",
                        "message": "AI provider rate limit exceeded. Please try again later.",
                        "retry_after": 60,
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            logger.error(
                "RAG query failed for conversation %s: %s",
                conversation_id,
                e,
            )
            return Response(
                {"error": "rag_error", "message": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ------------------------------------------------------------------
        # 6. Persist the assistant message with sources and token_usage
        # ------------------------------------------------------------------
        assistant_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=result["content"],
            sources=result["sources"],
            token_usage=result["token_usage"],
        )

        # ------------------------------------------------------------------
        # 7. Touch conversation.updated_at
        # ------------------------------------------------------------------
        conversation.save()  # triggers auto_now=True

        # ------------------------------------------------------------------
        # 8. Return 201 Created with MessageSerializer of assistant message
        # ------------------------------------------------------------------
        response_serializer = MessageSerializer(assistant_message)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class DocumentDirectQueryView(APIView):
    """Handle stateless direct queries against a document.

    **Endpoint:** ``POST /documents/{document_id}/query``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **POST Responses:**
        - ``200 OK`` — Query answered successfully.
        - ``400 Bad Request`` — Validation error (empty question, invalid top_k, etc.).
        - ``401 Unauthorized`` — Missing or invalid authentication.
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
        - ``422 Unprocessable Entity`` — Document processing is not complete.
        - ``429 Too Many Requests`` — OpenAI API rate limit exceeded.
        - ``502 Bad Gateway`` — RAG service error.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: str) -> Response:
        """Handle the direct query POST request."""
        # ------------------------------------------------------------------
        # 1. Fetch document + ownership check
        # ------------------------------------------------------------------
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if document.user != request.user:
            return Response(
                {
                    "error": "permission_denied",
                    "message": "You do not have permission to access this document.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ------------------------------------------------------------------
        # 2. Validate document processing status
        # ------------------------------------------------------------------
        if document.processing_status != "completed":
            return Response(
                {
                    "error": "processing_incomplete",
                    "message": "Document processing is not complete. Please wait for processing to finish.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # ------------------------------------------------------------------
        # 3. Validate input with DirectQuerySerializer
        # ------------------------------------------------------------------
        serializer = DirectQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        question = validated_data["question"]
        top_k = validated_data.get("top_k", 5)

        # ------------------------------------------------------------------
        # 4. Call run_rag_query (stateless — no conversation history)
        # ------------------------------------------------------------------
        try:
            result = run_rag_query(
                question=question,
                document_id=str(document.id),
                conversation_history=[],
                top_k=top_k,
            )
        except RAGServiceException as e:
            error_msg = str(e).lower()
            if isinstance(e.__cause__, RateLimitError) or "rate limit" in error_msg or "429" in error_msg:
                return Response(
                    {
                        "error": "rate_limit_exceeded",
                        "message": "AI provider rate limit exceeded. Please try again later.",
                        "retry_after": 60,
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            logger.error(
                "Direct query RAG failed for document %s: %s",
                document_id,
                e,
            )
            return Response(
                {"error": "rag_error", "message": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ------------------------------------------------------------------
        # 5. Return 200 OK with answer, sources, token_usage
        #    NOTE: Do NOT persist any messages or conversations
        # ------------------------------------------------------------------
        return Response(
            {
                "answer": result["content"],
                "sources": result["sources"],
                "token_usage": result["token_usage"],
            },
            status=status.HTTP_200_OK,
        )
