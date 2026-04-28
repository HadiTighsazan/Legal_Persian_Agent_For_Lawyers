"""
Views for the conversations app.

Provides ``ConversationListCreateView`` (POST + GET /conversations/) and
``ConversationDetailView`` (GET + DELETE /conversations/{conversation_id})
for CRUD operations on conversations (Epic E-07, Task 4).
"""

from __future__ import annotations

import logging

from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.models import Conversation
from conversations.serializers import (
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
)

logger = logging.getLogger(__name__)


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

        # Pagination
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (ValueError, TypeError):
            page, page_size = 1, 20

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100

        total = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        page_conversations = queryset[start:end]

        serializer = ConversationListSerializer(page_conversations, many=True)

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return Response(
            {
                "count": total,
                "next": page + 1 if page < total_pages else None,
                "previous": page - 1 if page > 1 else None,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


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
    # Helper — Fetch conversation with ownership check
    # ------------------------------------------------------------------

    def _get_conversation_or_error(
        self,
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

    # ------------------------------------------------------------------
    # GET — Retrieve a single conversation with messages
    # ------------------------------------------------------------------

    def get(self, request: Request, conversation_id: str) -> Response:
        """Handle the conversation detail GET request."""
        conversation, error = self._get_conversation_or_error(
            conversation_id,
            request,
        )
        if error:
            return error

        # Prefetch messages and annotate message_count
        conversation = Conversation.objects.prefetch_related("messages").annotate(
            message_count=Count("messages"),
        ).get(id=conversation.id)

        serializer = ConversationDetailSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # DELETE — Delete a conversation
    # ------------------------------------------------------------------

    def delete(self, request: Request, conversation_id: str) -> Response:
        """Handle the conversation deletion DELETE request."""
        conversation, error = self._get_conversation_or_error(
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
