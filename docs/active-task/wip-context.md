# WIP Context — Purge & Re-import Legislation Hub (هاب قوانین مصوب)

## Status: ✅ COMPLETED — Implementation & Tests Verified

## Summary

A new management command [`reimport_legislation_hub`](src/backend/documents/management/commands/reimport_legislation_hub.py) has been implemented to:
1. **Purge** all existing data in the legislation hub (`hub_type='legislation'`)
2. **Re-import** pre-chunked JSON data from `C:\Users\starlap\Desktop\chunked_datasets\هاب قوانین مصوب\laws\` (~98-99 JSON files, one per law)

The JSON files are **Format B** (flat array of chunk objects) where each chunk has `chunk_id`, `text`, and `metadata.source` fields. Chunks are grouped by `metadata.source` (the law name) — one Document per unique law name.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| New command (not modifying existing) | Existing `import_chunked_data` groups by `full_title`/`parent_title`, but legislation files lack these fields |
| Group by `metadata.source` | Each JSON file represents one law; `metadata.source` contains the law name |
| Volume mount approach | Docker containers need access to host path; mapped to `/data/chunked_datasets` |
| CASCADE purge | Deleting legislation Documents cascades to chunks, conversations, tasks |
| `transaction.atomic()` per document | Ensures per-document transactional integrity |
| `bulk_create`/`bulk_update` | Efficient batch operations for chunks and embeddings |

### 5-Phase Architecture

| Phase | Description |
|-------|-------------|
| **Phase 1: Purge** | Delete all `hub_type='legislation'` documents (CASCADE handles chunks) |
| **Phase 2: Load** | Read and validate JSON files (Format B flat array, non-empty `text` field) |
| **Phase 3: Group** | Group chunks by `metadata.source` (law name) |
| **Phase 4: Create** | Create one Document per law + bulk create DocumentChunks with denormalized fields |
| **Phase 5: Embed** | Batch generate embeddings via `batch_generate_embeddings()` |

### Denormalized Fields on Chunks

| Field | Source |
|-------|--------|
| `law_name` | `metadata.source` |
| `legal_status` | `metadata.status` |
| `approval_date` | Parsed from `metadata.approval_date` (YYYY/MM/DD format) |
| `legal_type` | Defaults to `"article"` |
| `hub_type` | Always `"legislation"` |

### Metadata Preserved in Chunk Metadata

- `chunk_id` — Original chunk identifier
- `madde_number` — Article number
- `madde_suffix` — Article suffix
- `madde_raw` — Raw article text
- All original metadata fields (source, hub_type, approval_date, status, summary, kitab, bakhsh, fasl, etc.)

---

## Changes Made

### Files Modified

1. [`docker-compose.yml`](docker-compose.yml) — Added volume mount:
   ```yaml
   - C:/Users/starlap/Desktop/chunked_datasets:/data/chunked_datasets
   ```
   Applied to both `backend` and `celery_worker` services.

### Files Created

2. [`src/backend/documents/management/commands/reimport_legislation_hub.py`](src/backend/documents/management/commands/reimport_legislation_hub.py) — Full management command (678 lines) with:
   - `ReimportStats` dataclass tracking all phases
   - `Command` class with arguments: `--data-dir`, `--dry-run`, `--user-id`, `--embedding-batch-size`, `--skip-embedding`
   - 5-phase orchestration in `handle()`
   - Error handling with `CommandError` on early return paths

3. [`src/backend/documents/tests/test_reimport_legislation_hub.py`](src/backend/documents/tests/test_reimport_legislation_hub.py) — 20 test cases (948 lines):
   - Purge phase tests (2): existing data deletion, other hub isolation
   - Import phase tests (3): single file, multiple files, grouping by source
   - Denormalized fields tests (2): field population, hub_type correctness
   - Embedding tests (3): generation, skip flag, batch size
   - Dry-run test (1): no DB modifications
   - Error handling tests (4): missing text, invalid JSON, empty dir, non-existent dir, wrong format
   - Idempotency test (1): safe re-run
   - Metadata preservation test (1): all fields preserved
   - User assignment test (1): custom --user-id
   - No existing data test (1): works with empty DB

### Test Results

```
20 passed in 10.26s
```

---

## How to Use

### 1. Restart Docker containers (to pick up volume mount)

```bash
docker-compose down
docker-compose up -d
```

### 2. Dry-run (validate without writing)

```bash
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \
    --dry-run
```

### 3. Actual import

```bash
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws
```

### 4. Custom options

```bash
# Skip embedding (for testing)
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \
    --skip-embedding

# Custom embedding batch size
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \
    --embedding-batch-size 32

# Specify owner user
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \
    --user-id <UUID>
```

---

## Next Steps

1. Restart Docker containers to pick up the volume mount change
2. Run the dry-run command to validate
3. Run the actual import command
4. Verify the data in the database
