"""
Serializers for the documents app.

Provides ``DocumentUploadSerializer`` for validating incoming file uploads,
``DocumentResponseSerializer`` for formatting document metadata into
a consistent JSON response, and processing-status serializers for
:class:`~documents.views.DocumentProcessingStatusView`.
"""

from rest_framework import serializers


class DocumentUploadSerializer(serializers.Serializer):
    """Validate the incoming file and title fields from a multipart/form-data request.

    The serializer only performs basic DRF-level validation (ensuring a file
    is present and a title is provided).  Deeper type/size validation is
    delegated to the :mod:`documents.utils.file_validator` module called by
    the upload service.
    """

    file = serializers.FileField(
        help_text="The document file to upload (PDF, DOCX, or TXT).",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        default="",
        help_text="A descriptive title for the document.",
    )


class DocumentResponseSerializer(serializers.Serializer):
    """Format the document metadata dictionary into a consistent response.

    This serializer mirrors the dictionary returned by
    :func:`documents.services.upload_service.upload_document`.
    """

    id = serializers.UUIDField(
        help_text="Unique identifier of the document.",
    )
    title = serializers.CharField(
        help_text="Internal storage filename of the document.",
    )
    original_filename = serializers.CharField(
        help_text="Original name of the uploaded file.",
    )
    file_size = serializers.IntegerField(
        help_text="Size of the file in bytes.",
    )
    mime_type = serializers.CharField(
        help_text="MIME type of the file (e.g. application/pdf).",
    )
    file_path = serializers.CharField(
        help_text="Storage path where the file is persisted.",
    )
    storage_type = serializers.CharField(
        help_text="Storage backend used (e.g. local or s3).",
    )
    status = serializers.CharField(
        help_text="Current processing status of the document.",
    )
    created_at = serializers.DateTimeField(
        help_text="Timestamp when the document record was created.",
    )


class ProcessingTaskSerializer(serializers.Serializer):
    """Serialize a single :class:`~tasks.models.ProcessingTask` for the
    processing-status response."""

    task_type = serializers.CharField(
        help_text="Type of processing task (extract, chunk, embed).",
    )
    status = serializers.CharField(
        help_text="Current status of the task (pending, running, completed, failed).",
    )
    progress = serializers.IntegerField(
        help_text="Progress percentage (0–100).",
    )
    error_message = serializers.CharField(
        allow_null=True,
        help_text="Error message if the task failed, or null.",
    )


class ProcessingStatusSerializer(serializers.Serializer):
    """Serialize the full processing status response for a document."""

    document_id = serializers.UUIDField(
        help_text="Unique identifier of the document.",
    )
    status = serializers.CharField(
        help_text="Overall processing status of the document.",
    )
    progress = serializers.IntegerField(
        help_text="Aggregated progress percentage (average of all task progress values).",
    )
    tasks = ProcessingTaskSerializer(
        many=True,
        help_text="List of processing tasks for this document.",
    )


class DocumentChunkSerializer(serializers.Serializer):
    """Serialize a single DocumentChunk for the chunks list response."""

    id = serializers.UUIDField(
        help_text="Unique identifier of the chunk.",
    )
    chunk_index = serializers.IntegerField(
        help_text="Sequential index of the chunk within the document.",
    )
    page_start = serializers.IntegerField(
        help_text="Starting page number for this chunk.",
    )
    page_end = serializers.IntegerField(
        help_text="Ending page number for this chunk.",
    )
    content = serializers.CharField(
        help_text="Text content of the chunk.",
    )
    token_count = serializers.IntegerField(
        allow_null=True,
        help_text="Number of tokens in the chunk, or null if not computed.",
    )
    metadata = serializers.JSONField(
        help_text="Additional metadata associated with the chunk.",
    )


class DocumentEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /documents/{id}/embed.

    Returns task metadata immediately after triggering the embedding
    Celery task for all un-embedded chunks of a document.
    """

    task_id = serializers.UUIDField(
        help_text="UUID of the Celery task processing the embedding.",
    )
    task_type = serializers.CharField(
        default="embed",
        help_text="Type of processing task (always 'embed').",
    )
    status = serializers.CharField(
        default="pending",
        help_text="Initial status of the embedding task.",
    )
    document_id = serializers.UUIDField(
        help_text="UUID of the document being embedded.",
    )
    total_chunks = serializers.IntegerField(
        help_text="Number of chunks queued for embedding.",
    )


class ChunkBatchEmbedRequestSerializer(serializers.Serializer):
    """Validate the incoming chunk_ids list for batch embedding.

    Accepts a list of UUIDs identifying which chunks to embed.
    """

    chunk_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of chunk UUIDs to embed.",
    )


class ChunkBatchEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /chunks/batch-embed.

    Provides a summary of the batch embedding operation.
    """

    processed = serializers.IntegerField(
        help_text="Number of chunks successfully embedded.",
    )
    skipped = serializers.IntegerField(
        help_text="Number of chunks skipped (already had embeddings).",
    )
    failed = serializers.IntegerField(
        help_text="Number of chunks that failed to embed.",
    )


class ChunkReEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /chunks/{chunk_id}/re-embed.

    Indicates whether the chunk's embedding was successfully regenerated.
    """

    chunk_id = serializers.UUIDField(
        help_text="UUID of the chunk that was re-embedded.",
    )
    embedding_updated = serializers.BooleanField(
        help_text="Whether the embedding was successfully updated.",
    )


class SearchRequestSerializer(serializers.Serializer):
    """Validate the incoming search request body.

    Fields:
        query (str): Required search query text, max 1000 characters.
        top_k (int): Optional max results (default 10, range 1–50).
        min_score (float): Optional minimum relevance threshold
            (default 0.0, range 0.0–1.0).
        search_mode (str): Optional search mode — ``"hybrid"`` (default),
            ``"vector"``, ``"keyword"``, or ``"trigram"``.
        enable_trigram (bool): Optional flag to include trigram search in
            hybrid mode (default ``True``).
        filters (dict): Optional metadata filter conditions.
    """

    query = serializers.CharField(
        required=True,
        max_length=1000,
        help_text="Natural language search query.",
    )
    top_k = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text="Maximum number of search results to return (1–50).",
    )
    min_score = serializers.FloatField(
        required=False,
        default=0.0,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum relevance score threshold (0.0–1.0).",
    )
    search_mode = serializers.ChoiceField(
        required=False,
        default="hybrid",
        choices=["hybrid", "vector", "keyword", "trigram"],
        help_text=(
            "Search mode: 'hybrid' (vector + keyword + trigram with RRF fusion, "
            "default), "
            "'vector' (cosine similarity only), "
            "'keyword' (PostgreSQL full-text search only), "
            "'trigram' (PostgreSQL pg_trgm trigram similarity search)."
        ),
    )
    enable_trigram = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "When True (default) and search_mode='hybrid', includes trigram "
            "similarity search as a third retrieval method alongside vector "
            "and keyword search.  Set to False to use only vector + keyword."
        ),
    )
    filters = serializers.JSONField(
        required=False,
        default=None,
        allow_null=True,
        help_text=(
            "Optional metadata filter conditions. "
            "Supported fields: law_name, legal_status, approval_date, legal_type. "
            "Example: {\"legal_status\": \"valid\", \"law_name\": \"قانون مدنی\"}"
        ),
    )


class SearchResultSerializer(serializers.Serializer):
    """Serialize a single search result chunk.

    Mirrors the dict returned by
    :func:`~documents.services.search_service.search_chunks`,
    :func:`~documents.services.search_service.hybrid_search`,
    :func:`~documents.services.search_service.keyword_search`, or
    :func:`~documents.services.search_service.trigram_search`.
    """

    chunk_id = serializers.UUIDField(
        help_text="Unique identifier of the matching chunk.",
    )
    chunk_index = serializers.IntegerField(
        help_text="Sequential index of the chunk within the document.",
    )
    page_start = serializers.IntegerField(
        help_text="Starting page number for this chunk.",
    )
    page_end = serializers.IntegerField(
        help_text="Ending page number for this chunk.",
    )
    content = serializers.CharField(
        help_text="Text content of the chunk.",
    )
    relevance_score = serializers.FloatField(
        help_text=(
            "Relevance score. For 'vector' mode: cosine similarity (0.0–1.0). "
            "For 'keyword' mode: FTS rank. "
            "For 'trigram' mode: trigram similarity (0.0–1.0). "
            "For 'hybrid' mode: RRF fused score."
        ),
    )
    token_count = serializers.IntegerField(
        allow_null=True,
        help_text="Number of tokens in the chunk, or null if not computed.",
    )
    metadata = serializers.JSONField(
        help_text="Additional metadata associated with the chunk.",
    )
    legal_context = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        help_text="Human-readable legal context string for RAG.",
    )
    vector_score = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Original vector similarity score. "
            "Only present in 'hybrid' mode results."
        ),
    )
    keyword_score = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Original keyword FTS rank score. "
            "Only present in 'hybrid' mode results."
        ),
    )
    trigram_score = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Original trigram similarity score. "
            "Only present in 'hybrid' mode results."
        ),
    )
    rrf_score = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Reciprocal Rank Fusion score. "
            "Only present in 'hybrid' mode results."
        ),
    )


class SearchResponseSerializer(serializers.Serializer):
    """Serialize the full search response.

    Wraps a list of :class:`SearchResultSerializer` instances along with
    the original request parameters and result count.
    """

    results = SearchResultSerializer(
        many=True,
        help_text="List of matching chunks ordered by relevance.",
    )
    query = serializers.CharField(
        help_text="The original search query.",
    )
    top_k = serializers.IntegerField(
        help_text="Maximum number of results requested.",
    )
    min_score = serializers.FloatField(
        help_text="Minimum relevance score threshold used.",
    )
    search_mode = serializers.CharField(
        required=False,
        default="hybrid",
        help_text=(
            "Search mode used ('hybrid', 'vector', 'keyword', or 'trigram')."
        ),
    )
    enable_trigram = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether trigram search was included in hybrid mode."
        ),
    )
    filters = serializers.JSONField(
        allow_null=True,
        required=False,
        default=None,
        help_text="Metadata filter conditions applied.",
    )
    total_results = serializers.IntegerField(
        help_text="Total number of results returned.",
    )
