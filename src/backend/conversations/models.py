"""
Conversation models for the DocuChat system.
"""
import uuid

from django.db import models
from django.utils import timezone

from documents.models import Document
from users.models import User


class Conversation(models.Model):
    """
    Conversation model for Q&A sessions about documents.

    ``document`` is nullable to support Global RAG conversations that are not
    tied to any specific user-uploaded document.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name='conversations',
        null=True, blank=True,
    )
    title = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'conversations'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['document']),
            models.Index(fields=['updated_at']),
        ]
    
    def __str__(self):
        if self.document:
            return f"Conversation about {self.document.title} ({self.user.email})"
        return f"Global RAG Conversation ({self.user.email})"


class Message(models.Model):
    """
    Message model for conversation messages.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list)  # Array of source chunks used
    token_usage = models.JSONField(null=True, blank=True)  # Token usage stats
    hub_metadata = models.JSONField(
        null=True, blank=True, default=None,
        help_text="Metadata for Global RAG queries: stores per-hub results, "
                  "sub-queries, and hub-level token usage.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'messages'
        indexes = [
            models.Index(fields=['conversation']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."