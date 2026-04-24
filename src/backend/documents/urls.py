"""
URL configuration for the documents app.

Registers the ``upload/``, ``process/``, and ``processing-status/`` routes.
"""

from django.urls import path

from documents.views import (
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
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
]
