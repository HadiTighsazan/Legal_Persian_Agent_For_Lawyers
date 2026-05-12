# WIP Context — Phase 2a Completion & Data Injection

## Status: ✅ COMPLETED (2026-05-12)

## Summary

Completed Phase 2a (Global RAG Lite) implementation by creating the `import_chunked_data` management command, writing 19 tests, and injecting 6 pre-chunked Persian legal datasets into the 3 knowledge hubs.

---

## Step 1: Created `import_chunked_data` Management Command

**File:** [`src/backend/documents/management/commands/import_chunked_data.py`](src/backend/documents/management/commands/import_chunked_data.py)

- Supports 3 auto-detected JSON formats (A: legislation object, B: precedent flat array, C: advisory flat array)
- Folder-to-hub mapping: `"هاب قوانین مصوب"` → `legislation`, `"هاب رویه های قضایی"` → `judicial_precedent`, `"هاب نظریات مشورتی و رویه عملی"` → `advisory_opinion`
- Hub type normalization: `"precedent"` → `"judicial_precedent"`, `"advisory"` → `"advisory_opinion"`
- Idempotency via `metadata__chunk_id` lookup on `DocumentChunk`
- Transactional atomicity per document group
- Configurable embedding batch size (default 16 for bge-m3 on 4GB VRAM)
- Dry-run mode (`--dry-run`)
- User assignment via `--user-id`

## Step 2: Wrote 19 Tests

**File:** [`src/backend/documents/tests/test_import_chunked_data.py`](src/backend/documents/tests/test_import_chunked_data.py)

All 19 tests pass, covering:
- Format A/B/C ingestion
- All folder-to-hub mappings
- Hub type normalization
- Dry-run mode
- Idempotency (re-running skips existing chunks)
- Transactional rollback on failure
- Missing text field handling
- Invalid JSON handling
- Unknown folder rejection
- Non-existent directory error
- User-id parameter
- Multiple files in a folder
- Format detection
- Embedding batch size parameter
- Empty chunks array handling
- Format B multiple documents grouping

## Step 3: Migrations

All migrations already applied. No pending migrations.

## Step 4: Existing Tests

All 55 existing Phase 2a tests pass (no regressions).

## Step 5: Data Injection

Injected 6 pre-chunked JSON files from `C:\Users\starlap\Desktop\chunked_datasets` into the Docker container at `/data/chunked_datasets/`.

**Dry-run result:** 6 files processed, 3,074 documents, 18,935 chunks
**Actual import result:** 6 files processed, 3,072 documents, 18,927 chunks, 18,927 embedded, 2 skipped

## Step 6: Verified Data Injection

| Hub Type | Documents | Chunks |
|---|---|---|
| `legislation` | 2 | 4,612 |
| `judicial_precedent` | 1,301 | 5,865 |
| `advisory_opinion` | 1,769 | 8,450 |
| **Total** | **3,072** | **18,927** |

All chunks have embeddings populated (not null).

## Step 7: Updated Reference Documentation

- [`docs/references/database-schema.md`](docs/references/database-schema.md): Added Management Commands section documenting `import_chunked_data`, folder-to-hub mapping, data formats, idempotency, transactional integrity, embedding strategy, usage, and injected data summary.
- [`docs/references/api-registry.md`](docs/references/api-registry.md): No changes needed — Global RAG endpoint (`mode="global_rag"`) and `hub_metadata` response format already thoroughly documented.
- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md): This file.

## Step 8: End-to-End Verification — ✅ PASSED

Tested the full Global RAG pipeline by sending a Persian legal query:

**Query:** `"مجازات جعل اسناد رسمی چیست؟"` (What is the punishment for forgery of official documents?)

**Result:** ✅ All 3 hubs returned results with no errors:

| Hub | Chunks Retrieved | Key Sources Cited |
|---|---|---|
| `legislation` | 10 | ماده 525 (حبس ۱-۱۰ سال), مواد 532-534 (کارمندان دولت), مواد 100-103 قانون ثبت |
| `judicial_precedent` | 10 | رأی وحدت رویه شماره ۶۲۴ (تفکیک جرم جعل و استفاده از سند مجعول) |
| `advisory_opinion` | 10 | نظریات مشورتی مرتبط |

**Response highlights:**
- LLM correctly differentiated punishments by perpetrator type (ordinary citizens, government employees, registry staff)
- Cited specific legal articles with article numbers
- Referenced judicial precedent (binding unified precedent)
- Included a summary table
- `hub_metadata` fully populated with per-hub sub-queries, chunk counts, and no errors
- Token usage: 6,703 prompt + 1,000 completion = 7,703 total tokens
- `sources` array returned empty (expected — sources are embedded in the LLM response text via citation markers)

**Phase 2a (Global RAG Lite) is now COMPLETE.**

---

## Files Created

| File | Description |
|---|---|
| [`src/backend/documents/management/commands/import_chunked_data.py`](src/backend/documents/management/commands/import_chunked_data.py) | Management command for importing pre-chunked JSON datasets |
| [`src/backend/documents/tests/test_import_chunked_data.py`](src/backend/documents/tests/test_import_chunked_data.py) | 19 tests for the import_chunked_data command |

## Files Modified

| File | Description |
|---|---|
| [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added Management Commands section with import_chunked_data documentation |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | This file — recorded Phase 2a completion |

## Next Steps

1. Run end-to-end verification: send a Global RAG query via the API and verify multi-hub response
2. If verification passes, Phase 2a is complete
