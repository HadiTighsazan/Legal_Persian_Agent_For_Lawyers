# Task 5: Register Embedding Routes — Implementation Prompt

## Context

Task 4 (Embedding Views) is already ✅ **completed**. The following already exist:

- [`src/backend/documents/views.py`](src/backend/documents/views.py) — All 4 views: `DocumentEmbedView`, `ChunkBatchEmbedView`, `ChunkReEmbedView`, `TaskStatusView`
- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — All routes including `document-embed`, `chunk-batch-embed`, `chunk-re-embed`, AND `task-status`
- [`src/backend/tasks/`](src/backend/tasks/) — App exists with [`models.py`](src/backend/tasks/models.py) but **no `urls.py`**

**What remains for Task 5:** Move the `TaskStatusView` route from `documents/urls.py` into a new `tasks/urls.py`, register it in the root `config/urls.py`, and update reference docs.

---

## Changes Required

### 1. Create `src/backend/tasks/urls.py` (NEW FILE)

```python
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
```

**Note:** The import comes from `documents.views` since `TaskStatusView` lives there (it's a document-related view). This is fine — Django allows cross-app URL registration.

---

### 2. Modify `src/backend/documents/urls.py`

**Remove** the `TaskStatusView` import and its route (lines 19, 61-65), since it's moving to `tasks/urls.py`.

**Before:**
```python
from documents.views import (
    ChunkBatchEmbedView,
    ChunkReEmbedView,
    DocumentChunksListView,
    DocumentEmbedView,
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
    ProcessingTaskRetryView,
    TaskStatusView,          # ← REMOVE this import
)

urlpatterns = [
    # ... existing routes ...
    path(
        "tasks/<uuid:task_id>/",
        TaskStatusView.as_view(),   # ← REMOVE this route
        name="task-status",
    ),
]
```

**After:**
```python
from documents.views import (
    ChunkBatchEmbedView,
    ChunkReEmbedView,
    DocumentChunksListView,
    DocumentEmbedView,
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
    ProcessingTaskRetryView,
    # TaskStatusView removed — moved to tasks/urls.py
)

urlpatterns = [
    # ... existing routes ...
    # task-status route removed — moved to tasks/urls.py
]
```

Also update the module docstring to remove mention of `tasks/` routes.

---

### 3. Modify `src/backend/config/urls.py`

**Uncomment** the `tasks/` include line (currently line 58):

**Before:**
```python
# path('api/v1/tasks/', include('tasks.urls', namespace='tasks')),
```

**After:**
```python
path('tasks/', include('tasks.urls')),
```

**Note:** Use `'tasks/'` (not `'api/v1/tasks/'`) to match the existing pattern used by `documents/` on line 56. The `/api/` prefix is handled by Nginx proxy, not Django.

---

### 4. Update `docs/references/api-registry.md`

The `GET /tasks/{task_id}/` endpoint is already documented in the registry (lines 595-621). Update the **URL path** from `/documents/tasks/{task_id}/` to `/tasks/{task_id}/` to reflect the new routing.

Also update the "Tasks & Processing" section (lines 827-858) similarly.

---

### 5. Update `docs/active-task/wip-context.md`

Record that Task 5 is complete with:
- What was done (created `tasks/urls.py`, modified `documents/urls.py` and `config/urls.py`)
- The new URL structure
- Next steps (proceed to Task 6 or next planned task)

---

## Verification Checklist

After implementation, verify:

- [ ] `docker-compose exec backend python manage.py show_urls` shows `tasks/<uuid:task_id>/` → `TaskStatusView`
- [ ] `docker-compose exec backend python manage.py show_urls` does NOT show `documents/tasks/<uuid:task_id>/`
- [ ] `docker-compose exec backend python manage.py check` passes with no errors
- [ ] Existing tests still pass: `docker-compose exec backend pytest`
- [ ] `GET /tasks/{task_id}/` returns `200 OK` for a valid task
- [ ] `GET /tasks/{task_id}/` returns `404 Not Found` for a non-existent task

---

## Mermaid Diagram: URL Resolution Flow

```mermaid
flowchart LR
    Client -->|GET /tasks/{task_id}| Nginx
    Nginx -->|/api/tasks/{task_id}| Django
    Django -->|tasks/urls.py| TaskStatusView
    TaskStatusView -->|ProcessingTask.objects.get| Database

    subgraph "config/urls.py"
        Root["path'tasks/', include'tasks.urls'"]
    end

    subgraph "tasks/urls.py"
        TaskRoute["path'<uuid:task_id>/', TaskStatusView"]
    end
```

---

## Notes

- The `TaskStatusView` class stays in `documents/views.py` — only the **route registration** moves to `tasks/urls.py`
- The `tasks` app already exists with `models.py` and `migrations/` — no new app creation needed
- No new views, serializers, or models are needed for this task
- The `ProcessingTaskRetryView` route (`processing-tasks/<uuid:task_id>/retry/`) stays in `documents/urls.py` since it's document-specific
