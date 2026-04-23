"""
URL configuration for the documents app.

Registers the ``upload/`` route and connects it to ``DocumentUploadView``.
"""

from django.urls import path

from documents.views import DocumentUploadView

app_name = "documents"

urlpatterns = [
    path("upload/", DocumentUploadView.as_view(), name="document-upload"),
]
