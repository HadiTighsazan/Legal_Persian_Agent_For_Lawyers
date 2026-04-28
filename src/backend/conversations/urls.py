"""
URL configuration for the conversations app.

Registers the ``/`` (list-create) and ``/<uuid:conversation_id>/`` (detail) routes.
"""

from django.urls import path

from conversations.views import ConversationDetailView, ConversationListCreateView

app_name = "conversations"

urlpatterns = [
    path(
        "",
        ConversationListCreateView.as_view(),
        name="conversation-list-create",
    ),
    path(
        "<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
]
