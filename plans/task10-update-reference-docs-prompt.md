# Task 10 — Update Reference Documentation

## Objective

Update the three reference documentation files to reflect the completed Epic E-05 embedding implementation. The code is already written and tested — this task is purely about documentation accuracy.

---

## Files to Modify

### 1. [`docs/references/database-schema.md`](docs/references/database-schema.md)

**What to check/confirm:**

- The `embedding` column in the `document_chunks` table (section **3. document_chunks**) must show `VECTOR(1536)` — NOT `TextField`. Currently it already shows `VECTOR(1536)` on line 62, so **confirm it's correct** (no change needed).
- Add a **Migration 0004** note under the Migration Notes section (after line 209) if not already present. Currently it exists on lines 203-209. **Confirm it's accurate** — it should mention:
  - Added `pgvector.django` to `INSTALLED_APPS`
  - Changed `embedding` column from `TEXT` to `VECTOR(1536)` via `VectorField`
  - Created `idx_chunks_embedding` ivfflat index
  - Added `openai>=1.0.0` and `pgvector>=0.2.0` to `requirements.txt`

**Actual state (verified from source):**
- [`src/backend/documents/models.py`](src/backend/documents/models.py:91): `embedding = VectorField(dimensions=1536, null=True, blank=True)` ✅ Correct
- [`src/backend/documents/migrations/0004_alter_documentchunk_embedding.py`](src/backend/documents/migrations/0004_alter_documentchunk_embedding.py): Migration exists ✅
- [`src/backend/documents/checks.py`](src/backend/documents/checks.py): System check for ivfflat index exists ✅

**Action:** No changes needed to `database-schema.md` — it's already correct.

---

### 2. [`docs/references/api-registry.md`](docs/references/api-registry.md)

**What to add:**

The 4 new embedding endpoints are already documented in the file (lines 513-621) under the section `### ✅ Implemented Endpoints — Embedding Views (Epic E-05, Task 4)`. However, verify and ensure the following are accurate:

#### Endpoint 1: `POST /documents/{document_id}/embed/`
- **View:** [`DocumentEmbedView`](src/backend/documents/views.py:426)
- **URL:** [`documents/<uuid:document_id>/embed/`](src/backend/documents/urls.py:40-44)
- **Response:** `202 Accepted` with `task_id`, `task_type`, `status`, `document_id`, `total_chunks`
- **Serializer:** [`DocumentEmbedResponseSerializer`](src/backend/documents/serializers.py:126)
- **Celery task:** [`embed_document.delay()`](src/backend/documents/views.py:470) dispatches [`embed_document`](src/backend/documents/tasks/embedding_tasks.py:38)

#### Endpoint 2: `POST /chunks/batch-embed/`
- **View:** [`ChunkBatchEmbedView`](src/backend/documents/views.py:492)
- **URL:** [`documents/chunks/batch-embed/`](src/backend/documents/urls.py:50-54)
- **Request:** `{"chunk_ids": ["<uuid>", ...]}`
- **Serializer:** [`ChunkBatchEmbedRequestSerializer`](src/backend/documents/serializers.py:152)
- **Response:** `200 OK` with `{"processed": N, "skipped": N, "failed": N}`
- **Response Serializer:** [`ChunkBatchEmbedResponseSerializer`](src/backend/documents/serializers.py:164)

#### Endpoint 3: `POST /chunks/{chunk_id}/re-embed/`
- **View:** [`ChunkReEmbedView`](src/backend/documents/views.py:522)
- **URL:** [`documents/chunks/<uuid:chunk_id>/re-embed/`](src/backend/documents/urls.py:55-59)
- **Response:** `200 OK` with `{"chunk_id": "uuid", "embedding_updated": true}`
- **Serializer:** [`ChunkReEmbedResponseSerializer`](src/backend/documents/serializers.py:181)

#### Endpoint 4: `GET /tasks/{task_id}/`
- **View:** [`TaskStatusView`](src/backend/documents/views.py:560)
- **URL:** [`tasks/<uuid:task_id>/`](src/backend/tasks/urls.py:13-15) — registered in `tasks/urls.py`, included from [`config/urls.py`](src/backend/config/urls.py:58) via `path('tasks/', include('tasks.urls'))`
- **Response:** `200 OK` with `id`, `document_id`, `task_type`, `status`, `progress`, `result`, `error_message`, `started_at`, `completed_at`

**Action:** The endpoints are already documented. **Verify accuracy** of the existing docs against the source code above. If any detail is wrong (e.g., URL patterns, field names, response codes), fix it.

---

### 3. [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md)

**What to do:**

Overwrite the entire file with the new WIP context for Task 10. The current content describes Task 9 (test consolidation) which is already completed.

The new WIP context should document:
1. **What was completed:** Task 10 — Updated all 3 reference documentation files
2. **Changes made to each file:**
   - `database-schema.md`: Confirmed `VECTOR(1536)` is correct; no changes needed
   - `api-registry.md`: Verified 4 embedding endpoints are accurately documented; made any corrections if needed
   - `wip-context.md`: Updated to reflect Task 10 completion
3. **Current state:** All Epic E-05 tasks (1-10) are now complete
4. **Next steps:** No further steps required for Epic E-05

---

## Execution Order

| Step | File | Action |
|------|------|--------|
| 1 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | **Verify** — confirm `VECTOR(1536)` on line 62 is correct; confirm Migration 0004 notes on lines 203-209 are accurate |
| 2 | [`docs/references/api-registry.md`](docs/references/api-registry.md) | **Verify & fix** — cross-check the 4 embedding endpoint docs (lines 513-621) against actual source code; correct any inaccuracies |
| 3 | [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | **Overwrite** — replace Task 9 content with Task 10 completion summary |

---

## Verification Checklist

After making changes, verify:

- [ ] `database-schema.md` line 62: `embedding` column type is `VECTOR(1536)` ✅
- [ ] `database-schema.md` Migration 0004 section accurately describes the changes
- [ ] `api-registry.md` has all 4 embedding endpoints with correct URL patterns
- [ ] `api-registry.md` has correct request/response schemas for each endpoint
- [ ] `api-registry.md` references the correct view class names and serializer names
- [ ] `wip-context.md` accurately reflects Task 10 completion
- [ ] All file paths in the docs use correct relative paths from project root
