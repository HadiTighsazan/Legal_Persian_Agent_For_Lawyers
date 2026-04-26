"""
URL configuration for the documents app.

Registers the ``upload/``, ``process/``, ``processing-status/``, and
``chunks/`` routes.
"""

from django.urls import path

from documents.views import (
    DocumentChunksListView,
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
    ProcessingTaskRetryView,
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
        "processing-tasks/<uuid:task_id>/retry/",
        ProcessingTaskRetryView.as_view(),
        name="processing-task-retry",
    ),
]
