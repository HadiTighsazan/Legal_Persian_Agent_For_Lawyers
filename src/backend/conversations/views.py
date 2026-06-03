"""
Views for the conversations app.

Provides ``ConversationListCreateView`` (POST + GET /conversations/),
``ConversationDetailView`` (GET + PATCH + DELETE /conversations/{conversation_id}),
``ConversationMessageView`` (POST /conversations/{conversation_id}/messages/),
and ``ConversationMessageStreamView`` (POST /conversations/{conversation_id}/messages/stream/)
for CRUD operations on conversations and asking questions (Epic E-07, Tasks 4 & 5).
"""

from __future__ import annotations

import json
import logging

from django.db.models import Count
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.models import Conversation, Message
from documents.models import Document
from conversations.global_rag_service import (
    GlobalRAGServiceException,
    run_global_rag_query,
    run_global_rag_query_stream,
)
from conversations.rag_service import RAGServiceException, run_rag_query, run_rag_query_stream
from conversations.serializers import (
    AskQuestionSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    DirectQuerySerializer,
    MessageSerializer,
)
from conversations.strategist_service import strategist_service
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
        document = validated_data.get("document_id")  # Document instance or None
        title = validated_data.get("title", "")

        conversation = Conversation.objects.create(
            user=request.user,
            document=document,
            title=title,
        )

        if document:
            logger.info(
                "Conversation %s created for user=%s, document=%s",
                conversation.id,
                request.user,
                document.id,
            )
        else:
            logger.info(
                "Global RAG conversation %s created for user=%s",
                conversation.id,
                request.user,
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

        # Optional filter by mode (e.g., ?mode=strategist, ?mode=global_rag)
        mode = request.query_params.get("mode")
        if mode:
            queryset = queryset.filter(mode=mode)

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
    """Retrieve, update, or delete a conversation.

    **Endpoint:** ``GET /conversations/{conversation_id}/``,
    ``PATCH /conversations/{conversation_id}/``, and
    ``DELETE /conversations/{conversation_id}/``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **GET Responses:**
        - ``200 OK`` — Conversation returned successfully.
        - ``403 Forbidden`` — Conversation belongs to another user.
        - ``404 Not Found`` — Conversation does not exist.
        - ``401 Unauthorized`` — Missing or invalid authentication.

    **PATCH Responses:**
        - ``200 OK`` — Conversation title updated successfully.
        - ``400 Bad Request`` — Title is empty or invalid.
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
    # PATCH — Update conversation title (rename)
    # ------------------------------------------------------------------

    def patch(self, request: Request, conversation_id: str) -> Response:
        """Handle the conversation rename PATCH request."""
        conversation, error = _get_conversation_or_error(
            conversation_id,
            request,
        )
        if error:
            return error

        title = request.data.get("title", "").strip()
        if not title:
            return Response(
                {
                    "error": "validation_error",
                    "message": "Title cannot be empty.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation.title = title
        conversation.save(update_fields=["title"])

        logger.info(
            "Conversation %s renamed to '%s' by user=%s",
            conversation_id,
            title,
            request.user,
        )

        serializer = ConversationListSerializer(conversation)
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
        mode = validated_data.get("mode", "global_rag")

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
        # 5. Validate mode compatibility with conversation type
        # ------------------------------------------------------------------
        if mode == "local_rag" and conversation.document is None:
            return Response(
                {
                    "error": "validation_error",
                    "message": "Local RAG requires a document. Use global_rag mode or create a conversation with a document.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ------------------------------------------------------------------
        # 6. Route to the appropriate pipeline based on mode
        # ------------------------------------------------------------------
        if mode == "strategist":
            # Strategist mode — use the strategist service (stub for now)
            try:
                # Collect all tokens from the streaming generator
                full_content = ""
                for event_type, data in strategist_service.process_message(
                    message=question,
                    conversation_history=conversation_history,
                ):
                    if event_type == "token":
                        full_content += data["content"]
                    elif event_type == "done":
                        result = {
                            "content": data["content"],
                            "sources": data.get("sources", []),
                            "token_usage": data.get(
                                "token_usage",
                                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                            ),
                        }
            except Exception as e:
                logger.error(
                    "Strategist processing failed for conversation %s: %s",
                    conversation_id,
                    e,
                )
                return Response(
                    {"error": "strategist_error", "message": str(e)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
        elif mode == "global_rag":
            try:
                result = run_global_rag_query(
                    question=question,
                    conversation_history=conversation_history,
                    top_k_per_hub=5,
                )
            except GlobalRAGServiceException as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg or "429" in error_msg:
                    return Response(
                        {
                            "error": "rate_limit_exceeded",
                            "message": "AI provider rate limit exceeded. Please try again later.",
                            "retry_after": 60,
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
                logger.error(
                    "Global RAG query failed for conversation %s: %s",
                    conversation_id,
                    e,
                )
                return Response(
                    {"error": "global_rag_error", "message": str(e)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
        else:
            try:
                result = run_rag_query(
                    question=question,
                    document_id=str(conversation.document_id),
                    conversation_history=conversation_history,
                    top_k=15,
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
        # 7. Persist the assistant message with sources, token_usage, and hub_metadata
        # ------------------------------------------------------------------
        assistant_kwargs = {
            "conversation": conversation,
            "role": "assistant",
            "content": result["content"],
            "sources": result["sources"],
            "token_usage": result["token_usage"],
        }
        if mode == "global_rag" and "hub_metadata" in result:
            assistant_kwargs["hub_metadata"] = result["hub_metadata"]
        assistant_message = Message.objects.create(**assistant_kwargs)

        # ------------------------------------------------------------------
        # 8. Touch conversation.updated_at
        # ------------------------------------------------------------------
        conversation.save()  # triggers auto_now=True

        # ------------------------------------------------------------------
        # 9. Return 201 Created with MessageSerializer of assistant message
        # ------------------------------------------------------------------
        response_serializer = MessageSerializer(assistant_message)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class ConversationMessageStreamView(APIView):
    """Handle asking a question with a streaming SSE response.

    **Endpoint:** ``POST /conversations/{conversation_id}/messages/stream/``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    Returns a ``text/event-stream`` response where each event is a JSON line
    prefixed with ``data: ``.

    **Event types:**
        - ``data: {"type": "token", "content": "..."}`` — A content token.
        - ``data: {"type": "done", "message_id": "...", "sources": [...], "token_usage": {...}}``
          — Streaming complete.

    **POST Responses:**
        - ``200 OK`` — SSE stream of tokens.
        - ``400 Bad Request`` — Validation error (empty content, etc.).
        - ``401 Unauthorized`` — Missing or invalid authentication.
        - ``403 Forbidden`` — Conversation belongs to another user.
        - ``404 Not Found`` — Conversation does not exist.
        - ``429 Too Many Requests`` — OpenAI API rate limit exceeded.
        - ``502 Bad Gateway`` — RAG service error.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, conversation_id: str) -> Response:
        """Handle the streaming question-asking POST request."""
        # 1. Fetch conversation + ownership check
        conversation, error = _get_conversation_or_error(conversation_id, request)
        if error:
            return error

        # 2. Validate input
        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        question = validated_data["content"]
        mode = validated_data.get("mode", "global_rag")

        # 3. Persist the user message
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=question,
        )

        # 4. Build conversation history
        all_messages = conversation.messages.all().order_by("created_at")
        conversation_history = [
            {"role": msg.role, "content": msg.content}
            for msg in all_messages
        ]

        # 5. Validate mode compatibility with conversation type
        if mode == "local_rag" and conversation.document is None:
            return Response(
                {
                    "error": "validation_error",
                    "message": "Local RAG requires a document. Use global_rag mode or create a conversation with a document.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 6. Create a streaming SSE response
        def event_stream():
            try:
                if mode == "strategist":
                    # Strategist mode — streaming mock response
                    logger.info(
                        "event_stream: Starting strategist stream for conversation %s",
                        conversation_id,
                    )
                    full_content: str = ""
                    final_token_usage: dict | None = None
                    final_sources: list = []

                    for event_type, data in strategist_service.process_message(
                        message=question,
                        conversation_history=conversation_history,
                    ):
                        if event_type == "token":
                            full_content += data["content"]
                            yield f"data: {json.dumps({'type': 'token', 'content': data['content']})}\n\n"
                        elif event_type == "done":
                            final_token_usage = data.get(
                                "token_usage",
                                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                            )
                            final_sources = data.get("sources", [])
                            logger.info(
                                "event_stream: Strategist done for conversation %s — %d chars",
                                conversation_id,
                                len(full_content),
                            )

                    # Persist the assistant message after streaming completes
                    assistant_message = Message.objects.create(
                        conversation=conversation,
                        role="assistant",
                        content=full_content,
                        sources=final_sources,
                        token_usage=final_token_usage,
                    )
                    conversation.save()

                    logger.info(
                        "event_stream: Strategist assistant message %s persisted for conversation %s",
                        assistant_message.id,
                        conversation_id,
                    )

                    yield f"data: {json.dumps({'type': 'done', 'message_id': str(assistant_message.id), 'sources': final_sources, 'token_usage': final_token_usage})}\n\n"
                elif mode == "global_rag":
                    # Global RAG with streaming synthesis
                    full_content: str = ""
                    final_token_usage: dict | None = None
                    final_sources: list = []
                    final_hub_metadata: dict | None = None

                    logger.info(
                        "event_stream: Starting global_rag stream for conversation %s",
                        conversation_id,
                    )
                    stream_gen = run_global_rag_query_stream(
                        question=question,
                        conversation_history=conversation_history,
                        top_k_per_hub=5,
                    )
                    logger.info(
                        "event_stream: run_global_rag_query_stream generator created for conversation %s",
                        conversation_id,
                    )

                    for event_type, data in stream_gen:
                        if event_type == "progress":
                            # Pass through progress events to the frontend (Fix 2: include reasoning)
                            yield f"data: {json.dumps({'type': 'progress', 'status': data['status'], 'reasoning': data.get('reasoning')})}\n\n"
                        elif event_type == "token":
                            full_content += data["content"]
                            yield f"data: {json.dumps({'type': 'token', 'content': data['content']})}\n\n"
                        elif event_type == "done":
                            final_token_usage = data.get("token_usage")
                            final_sources = data.get("sources", [])
                            final_hub_metadata = data.get("hub_metadata")
                            logger.info(
                                "event_stream: Global RAG done for conversation %s — %d chars, %d sources",
                                conversation_id,
                                len(full_content),
                                len(final_sources),
                            )

                    # Persist the assistant message after streaming completes
                    assistant_kwargs = {
                        "conversation": conversation,
                        "role": "assistant",
                        "content": full_content,
                        "sources": final_sources,
                        "token_usage": final_token_usage,
                    }
                    if final_hub_metadata:
                        assistant_kwargs["hub_metadata"] = final_hub_metadata
                    assistant_message = Message.objects.create(**assistant_kwargs)
                    conversation.save()

                    logger.info(
                        "event_stream: Assistant message %s persisted for conversation %s",
                        assistant_message.id,
                        conversation_id,
                    )

                    yield f"data: {json.dumps({'type': 'done', 'message_id': str(assistant_message.id), 'sources': final_sources, 'token_usage': final_token_usage, 'hub_metadata': final_hub_metadata})}\n\n"
                else:
                    logger.info(
                        "event_stream: Starting local_rag stream for conversation %s",
                        conversation_id,
                    )
                    for event_type, data in run_rag_query_stream(
                        question=question,
                        document_id=str(conversation.document_id),
                        conversation_history=conversation_history,
                        top_k=15,
                    ):
                        if event_type == "token":
                            yield f"data: {json.dumps({'type': 'token', 'content': data['content']})}\n\n"
                        elif event_type == "done":
                            # Persist the assistant message
                            assistant_message = Message.objects.create(
                                conversation=conversation,
                                role="assistant",
                                content=data["content"],
                                sources=data["sources"],
                                token_usage=data["token_usage"],
                            )
                            # Touch conversation.updated_at
                            conversation.save()

                            logger.info(
                                "event_stream: Local RAG done for conversation %s — message %s",
                                conversation_id,
                                assistant_message.id,
                            )

                            # Send done event with message metadata
                            yield f"data: {json.dumps({'type': 'done', 'message_id': str(assistant_message.id), 'sources': data['sources'], 'token_usage': data['token_usage']})}\n\n"

            except (RAGServiceException, GlobalRAGServiceException) as e:
                error_msg = str(e).lower()
                logger.exception(
                    "event_stream: RAGServiceException for conversation %s: %s",
                    conversation_id,
                    e,
                )
                if "rate limit" in error_msg or "429" in error_msg:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'rate_limit_exceeded', 'message': 'AI provider rate limit exceeded. Please try again later.'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'rag_error', 'message': str(e)})}\n\n"
            except Exception as e:
                logger.exception(
                    "event_stream: Unexpected error for conversation %s: %s",
                    conversation_id,
                    e,
                )
                yield f"data: {json.dumps({'type': 'error', 'error': 'internal_error', 'message': 'An unexpected error occurred.'})}\n\n"

        return StreamingHttpResponse(
            streaming_content=event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
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
        if document.status != "completed":
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
