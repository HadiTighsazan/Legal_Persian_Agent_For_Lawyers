"""
Document models for the DocuChat system.
"""
import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
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

    DOCUMENT_TYPE_CHOICES = [
        ('user_upload', 'User Upload'),
        ('reference_law', 'Reference Law'),
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
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default='user_upload',
        db_index=True,
        help_text="Type of document: 'user_upload' for regular files, "
                  "'reference_law' for system reference legal texts.",
    )
    
    # Document processing pipeline fields
    processing_status = models.CharField(max_length=20, default='pending')
    total_chunks = models.IntegerField(default=0)
    extracted_text_length = models.IntegerField(default=0)
    processing_error = models.TextField(null=True, blank=True)

    # Monitoring / debugging fields (added for monitoring page)
    extracted_text = models.TextField(blank=True, default="")
    extraction_method = models.CharField(max_length=20, null=True, blank=True)
    garbled_score = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'documents'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['document_type']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.user.email})"


class DocumentChunk(models.Model):
    """
    Document chunk model for storing text chunks with embeddings.

    Supports hybrid search (vector + keyword) via:

    - ``embedding`` — pgvector ``VectorField`` for semantic (cosine) similarity.
    - ``search_vector`` — PostgreSQL ``SearchVectorField`` for full-text keyword
      search using the ``simple`` configuration (exact token matching after
      lowercasing).
    - Denormalized metadata fields (``law_name``, ``legal_status``,
      ``approval_date``, ``legal_type``) for efficient SQL-level filtering
      without JSONB extraction overhead.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    page_start = models.IntegerField()
    page_end = models.IntegerField()
    content = models.TextField()
    token_count = models.IntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=768, null=True, blank=True)
    metadata = models.JSONField(default=dict)

    # ------------------------------------------------------------------
    # Full-Text Search (FTS) vector — populated by DB trigger
    # ------------------------------------------------------------------
    search_vector = SearchVectorField(null=True, blank=True, editable=False)

    # ------------------------------------------------------------------
    # Denormalized metadata fields for efficient filtering
    # ------------------------------------------------------------------
    law_name = models.CharField(max_length=500, null=True, blank=True, db_index=True)
    legal_status = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    approval_date = models.DateField(null=True, blank=True, db_index=True)
    legal_type = models.CharField(max_length=50, null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'document_chunks'
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['document', 'chunk_index']),
            # GIN index on search_vector for FTS performance
            GinIndex(fields=['search_vector'], name='chunk_search_vector_gin'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'chunk_index'],
                name='unique_document_chunk'
            )
        ]
    
    @property
    def legal_context(self) -> str:
        """Return a human-readable legal context string for RAG.

        Constructs a Persian legal context string from the chunk's metadata,
        useful for providing the LLM with article/chapter context during
        retrieval-augmented generation.

        Returns:
            A string like ``"قانون: نام قانون | فصل: ۱ | ماده: ۱"``,
            or an empty string if no legal metadata is present.
        """
        meta = self.metadata or {}
        parts: list[str] = []
        if meta.get("law_name"):
            parts.append(f"قانون: {meta['law_name']}")
        if meta.get("chapter"):
            parts.append(f"فصل: {meta['chapter']}")
        if meta.get("legal_number"):
            parts.append(f"ماده: {meta['legal_number']}")
        if meta.get("legal_type") == "note" and meta.get("parent_article"):
            parts.append(f"تبصره ماده {meta['parent_article']}")
        return " | ".join(parts)

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"