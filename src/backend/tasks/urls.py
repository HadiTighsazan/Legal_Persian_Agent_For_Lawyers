"""
URL configuration for the tasks app.

Registers the ``<uuid:task_id>/`` route for ``TaskStatusView``.
"""

from django.urls import path

from documents.views import TaskStatusView

app_name = "tasks"

urlpatterns = [
    path("<uuid:task_id>/", TaskStatusView.as_view(), name="task-status"),
]
