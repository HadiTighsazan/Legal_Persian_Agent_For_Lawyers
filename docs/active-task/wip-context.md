# WIP Context — Task 5 of Epic E-05 (Register Embedding Routes)

## Status: ✅ COMPLETED

## What Was Completed

### Source Code Modified

1. **`src/backend/tasks/urls.py`** (NEW FILE) — Created URL configuration for the tasks app:
   - Registers `<uuid:task_id>/` route pointing to `TaskStatusView`
   - Uses `app_name = "tasks"` for namespacing
   - Imports `TaskStatusView` from `documents.views` (cross-app import)

2. **`src/backend/documents/urls.py`** — Removed `TaskStatusView` import and its route:
   - Removed `TaskStatusView` from the import block (line 19)
   - Removed the `tasks/<uuid:task_id>/` → `TaskStatusView` route (lines 61-65)
   - Updated module docstring to remove mention of `tasks/` routes

3. **`src/backend/config/urls.py`** — Uncommented and activated the tasks app include:
   - Changed `# path('api/v1/tasks/', include('tasks.urls', namespace='tasks'))` to `path('tasks/', include('tasks.urls'))`
   - Uses `'tasks/'` prefix (not `'api/v1/tasks/'`) to match existing pattern used by `documents/`

### New URL Structure

| Method | URL Pattern | View | Source |
|--------|------------|------|--------|
| GET | `/tasks/{task_id}/` | `TaskStatusView` | `tasks/urls.py` |

The `TaskStatusView` class remains in `documents/views.py` — only the route registration moved to `tasks/urls.py`.

### Reference Docs Updated
- `docs/references/api-registry.md` — Already documented `/tasks/{task_id}/` correctly; no changes needed

## Next Steps
- Proceed to Task 6 (Chunks Retrieval API) or next planned task
