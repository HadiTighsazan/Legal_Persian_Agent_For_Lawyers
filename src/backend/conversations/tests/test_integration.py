"""
End-to-end integration tests for the conversations app.

Tests the full lifecycle: register user → create document → create conversation
→ ask questions → verify history → delete conversation.

Also tests the RAG service internals with mocked dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conversations.models import Conversation, Message
from conversations.rag_service import run_rag_query
from documents.models import Document, DocumentChunk
from users.models import User


class ConversationIntegrationTests(TestCase):
    """End-to-end integration tests for the conversations app."""

    MOCK_RAG_RESPONSE = {
        "content": "Based on the document, the answer is about machine learning.",
        "sources": [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 3,
                "content_preview": "Machine learning is...",
                "relevance_score": 0.95,
            }
        ],
        "token_usage": {"prompt_tokens": 350, "completion_tokens": 50, "total_tokens": 400},
        "raw_chunks": [],
    }

    def setUp(self):
        self.client = APIClient()
        # Step 1: Register user
        self.register_url = "/auth/register/"
        response = self.client.post(
            self.register_url,
            {
                "email": "integration@example.com",
                "password": "SecurePass123!",
                "full_name": "Integration Test",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.user_email = data["user"]["email"]
        self.access_token = data["accessToken"]
        self.auth_header = {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"}

        # Step 2: Create a processed document with chunks directly
        self.user = User.objects.get(email=self.user_email)
        self.document = Document.objects.create(
            user=self.user,
            title="integration-test-doc.pdf",
            filename="integration-test-doc.pdf",
            original_filename="integration-test-doc.pdf",
            file_path="/tmp/integration-test-doc.pdf",
            file_size=2048,
            mime_type="application/pdf",
            processing_status="completed",
            status="completed",
        )
        # Create chunks with mock embeddings
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=3,
            content="Machine learning is a subset of artificial intelligence.",
            token_count=10,
            embedding=[0.1] * 768,
        )
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=4,
            page_end=6,
            content="Deep learning uses neural networks with multiple layers.",
            token_count=8,
            embedding=[0.2] * 768,
        )

    # -- Test: Full conversation lifecycle ------------------------------------

    @patch("conversations.views.run_rag_query")
    def test_full_conversation_lifecycle(self, mock_run_rag_query):
        """Complete lifecycle: create conv → ask → verify → ask again → delete."""
        mock_run_rag_query.return_value = self.MOCK_RAG_RESPONSE

        # Step 3: Create conversation
        create_url = reverse("conversations:conversation-list-create")
        response = self.client.post(
            create_url,
            {"document_id": str(self.document.id), "title": "Integration Test Conv"},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        conv_data = response.json()
        conversation_id = conv_data["id"]
        self.assertEqual(conv_data["document_id"], str(self.document.id))

        # Step 4: POST first question
        messages_url = reverse(
            "conversations:conversation-messages",
            kwargs={"conversation_id": conversation_id},
        )
        response = self.client.post(
            messages_url,
            {"content": "What is machine learning?"},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        msg_data = response.json()
        self.assertEqual(msg_data["role"], "assistant")
        self.assertIn("machine learning", msg_data["content"].lower())
        self.assertGreater(len(msg_data["sources"]), 0)
        self.assertIn("token_usage", msg_data)

        # Step 5: GET conversation → verify 2 messages
        detail_url = reverse(
            "conversations:conversation-detail",
            kwargs={"conversation_id": conversation_id},
        )
        response = self.client.get(detail_url, **self.auth_header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        detail_data = response.json()
        self.assertEqual(detail_data["message_count"], 2)
        self.assertEqual(len(detail_data["messages"]), 2)
        self.assertEqual(detail_data["messages"][0]["role"], "user")
        self.assertEqual(
            detail_data["messages"][0]["content"], "What is machine learning?"
        )
        self.assertEqual(detail_data["messages"][1]["role"], "assistant")

        # Step 6: POST second question → verify history passed to RAG
        response = self.client.post(
            messages_url,
            {"content": "Tell me more about deep learning."},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify run_rag_query was called with conversation_history
        call_args = mock_run_rag_query.call_args
        self.assertIsNotNone(call_args)
        history = call_args.kwargs["conversation_history"]
        self.assertIsNotNone(history)
        # History should contain: first user msg + first assistant msg + second user msg
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "What is machine learning?")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[2]["role"], "user")
        self.assertEqual(history[2]["content"], "Tell me more about deep learning.")

        # Step 7: DELETE conversation
        response = self.client.delete(detail_url, **self.auth_header)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify conversation is deleted
        self.assertFalse(Conversation.objects.filter(id=conversation_id).exists())
        # Verify messages are cascade-deleted
        self.assertEqual(
            Message.objects.filter(conversation_id=conversation_id).count(), 0
        )

    # -- Test: RAG service integration with mocked internals ------------------

    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.get_chat_provider")
    def test_rag_service_integration(
        self, mock_get_chat_provider, mock_embed_query, mock_search_chunks
    ):
        """Test that run_rag_query correctly orchestrates embedding, search, and chat provider."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = [
            {
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 3,
                "content": "Machine learning is a subset of artificial intelligence.",
                "relevance_score": 0.95,
                "token_count": 10,
                "metadata": {},
            }
        ]
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "content": "Based on [Source 1], machine learning is a subset of AI.",
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        mock_get_chat_provider.return_value = mock_provider

        # Act
        result = run_rag_query(
            question="What is machine learning?",
            document_id=str(self.document.id),
            top_k=5,
        )

        # Assert
        self.assertIn("content", result)
        self.assertIn("sources", result)
        self.assertIn("token_usage", result)
        self.assertIn("raw_chunks", result)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["token_usage"]["total_tokens"], 150)
