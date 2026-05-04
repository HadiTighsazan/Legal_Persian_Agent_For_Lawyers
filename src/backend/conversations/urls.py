"""
URL configuration for the conversations app.

Registers the ``/`` (list-create), ``/<uuid:conversation_id>/`` (detail),
and ``/<uuid:conversation_id>/messages/`` (ask question) routes.
"""

from django.urls import path

from conversations.views import (
    ConversationDetailView,
    ConversationListCreateView,
    ConversationMessageView,
    ConversationMessageStreamView,
)

app_name = "conversations"

urlpatterns = [
    path(
        "",
        ConversationListCreateView.as_view(),
        name="conversation-list-create",
    ),
    path(
        "<uuid:conversation_id>/messages/",
        ConversationMessageView.as_view(),
        name="conversation-messages",
    ),
    path(
        "<uuid:conversation_id>/messages/stream/",
        ConversationMessageStreamView.as_view(),
        name="conversation-messages-stream",
    ),
    path(
        "<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
]
