"""
URL configuration for the documents app.

Registers the ``upload/``, ``process/``, ``processing-status/``, ``chunks/``,
``embed/``, ``batch-embed/``, ``re-embed/``, and ``tasks/`` routes.
"""

from django.urls import path

from documents.views import (
    ChunkBatchEmbedView,
    ChunkReEmbedView,
    DocumentChunksListView,
    DocumentEmbedView,
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
    ProcessingTaskRetryView,
    TaskStatusView,
)

app_name = "documents"

urlpatterns = [
    path("upload/", DocumentUploadView.as_view(), name="document-upload"),
    path(
        "<uuid:document_id>/process/",
        DocumentProcessView.as_view(),
        name="document-process",
    ),
    path(
        "<uuid:document_id>/processing-status/",
        DocumentProcessingStatusView.as_view(),
        name="document-processing-status",
    ),
    path(
        "<uuid:document_id>/chunks/",
        DocumentChunksListView.as_view(),
        name="document-chunks",
    ),
    path(
        "<uuid:document_id>/embed/",
        DocumentEmbedView.as_view(),
        name="document-embed",
    ),
    path(
        "processing-tasks/<uuid:task_id>/retry/",
        ProcessingTaskRetryView.as_view(),
        name="processing-task-retry",
    ),
    path(
        "chunks/batch-embed/",
        ChunkBatchEmbedView.as_view(),
        name="chunk-batch-embed",
    ),
    path(
        "chunks/<uuid:chunk_id>/re-embed/",
        ChunkReEmbedView.as_view(),
        name="chunk-re-embed",
    ),
    path(
        "tasks/<uuid:task_id>/",
        TaskStatusView.as_view(),
        name="task-status",
    ),
]
