"""
Document models for the DocuChat system.
"""
import uuid

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

from users.models import User


class Document(models.Model):
    """
    Document model representing uploaded files.

    The model has **two** status fields that serve different purposes:

    ``status``
        The **upload lifecycle** status.  Tracks whether the file has been
        uploaded, is being processed, is complete, or has failed.  Uses the
        :attr:`STATUS_CHOICES` enum (``uploaded`` / ``processing`` /
        ``completed`` / ``failed``).  This is the primary status consumers
        should check.

    ``processing_status``
        The **pipeline granular** status.  A free-text field (not constrained
        by choices) that reflects the state of the document-processing
        pipeline (``pending``, ``processing``, ``completed``, ``failed``).
        This field is set by the Celery tasks and is **not** the authoritative
        status for external consumers — use ``status`` for that.

    **Why two fields?**  The ``status`` field is the source of truth for API
    responses and external consumers.  The ``processing_status`` field exists
    for backward compatibility with earlier pipeline logic and is gradually
    being superseded by the :class:`~tasks.models.ProcessingTask` model, which
    tracks individual pipeline-step states.
    """
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=500)
    filename = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=500)
    file_path = models.CharField(max_length=1000)
    file_size = models.BigIntegerField()
    mime_type = models.CharField(max_length=100)
    storage_type = models.CharField(max_length=20, default="local", db_index=True)
    total_pages = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='uploaded')
    error_message = models.TextField(null=True, blank=True)
    
    # Document processing pipeline fields
    processing_status = models.CharField(max_length=20, default='pending')
    total_chunks = models.IntegerField(default=0)
    extracted_text_length = models.IntegerField(default=0)
    processing_error = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'documents'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.user.email})"


class DocumentChunk(models.Model):
    """
    Document chunk model for storing text chunks with embeddings.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    page_start = models.IntegerField()
    page_end = models.IntegerField()
    content = models.TextField()
    token_count = models.IntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'document_chunks'
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['document', 'chunk_index']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'chunk_index'],
                name='unique_document_chunk'
            )
        ]
    
    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"