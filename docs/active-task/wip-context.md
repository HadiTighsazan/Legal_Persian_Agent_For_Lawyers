# WIP Context — Phase 2a: Global RAG (Lite) Implementation

## Status: ✅ COMPLETED (2026-05-10) — Post-Audit Fixes Applied

## Summary

Implemented **Phase 2a — Global RAG (Lite)**, transforming the system from single-document Q&A to a multi-hub legal researcher. Users can now ask legal questions in Persian with `mode: "global_rag"` and the system queries three specialized legal knowledge hubs (Legislation, Judicial Precedent, Advisory Opinions) in parallel, then synthesizes a comprehensive answer with precise citations.

## What Was Built

### 1. Database Changes (Steps 1-2)

| File | Change |
|------|--------|
| [`src/backend/documents/models.py`](src/backend/documents/models.py) | Added `hub_type` CharField to `Document` and `DocumentChunk` (max_length=50, null=True, blank=True, db_index=True) with `HUB_TYPE_CHOICES` |
| [`src/backend/conversations/models.py`](src/backend/conversations/models.py) | Added `hub_metadata` JSONField to `Message` (null=True, blank=True, default=None) |
| [`src/backend/documents/migrations/0015_document_hub_type_documentchunk_hub_type_and_more.py`](src/backend/documents/migrations/0015_document_hub_type_documentchunk_hub_type_and_more.py) | Migration for hub_type fields (fixed to remove duplicate GIN index) |
| [`src/backend/conversations/migrations/0002_message_hub_metadata.py`](src/backend/conversations/migrations/0002_message_hub_metadata.py) | Migration for hub_metadata field |

### 2. Data Import (Step 3)

| File | Purpose |
|------|---------|
| [`src/backend/documents/management/commands/import_reference_laws.py`](src/backend/documents/management/commands/import_reference_laws.py) | Management command to import reference law JSON files with hub_type, uses ChunkingService + batch embeddings |

### 3. Cross-Document Search (Step 4)

| File | Change |
|------|--------|
| [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) | Added `_vector_search_by_hub()`, `_keyword_search_by_hub()`, `_trigram_search_by_hub()`, and `cross_document_hybrid_search()` — full hybrid search across all documents in a hub using RRF fusion |

### 4. Question Router (Step 5)

| File | Purpose |
|------|---------|
| [`src/backend/conversations/question_router.py`](src/backend/conversations/question_router.py) | LLM-powered question router that decomposes user queries and routes sub-queries to relevant legal hubs. Includes `route_question()`, `_parse_router_response()`, `_all_hubs_fallback()`, and `_build_router_messages()`. |

### 5. Global RAG Service (Steps 6-8)

| File | Purpose |
|------|---------|
| [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) | Full pipeline: `multi_hub_search()` → `build_global_context()` → `build_global_system_prompt()` → `run_global_rag_query()`. Includes RRF fusion per hub, global source numbering, token budget trimming, and hub_metadata extraction. |

### 6. API Changes (Steps 9-10)

| File | Change |
|------|--------|
| [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | Added `hub_metadata` to `MessageSerializer` (read-only). Added `mode` ChoiceField to `AskQuestionSerializer` with choices `local_rag`/`global_rag`, default `local_rag`. |
| [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | Updated `ConversationMessageView.post()` and `ConversationMessageStreamView.post()` to route to `run_global_rag_query()` when `mode="global_rag"`. Error handling for `GlobalRAGServiceException`. |

### 7. Documentation (Step 11)

| File | Change |
|------|--------|
| [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added hub_type columns, hub_metadata column, migration notes |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Added mode field docs, hub_metadata field, Global RAG response example |

### 8. Tests (Step 12)

| File | Tests |
|------|-------|
| [`src/backend/conversations/tests/test_question_router.py`](src/backend/conversations/tests/test_question_router.py) | 22 tests: BuildRouterMessagesTests (3), ParseRouterResponseTests (10), AllHubsFallbackTests (2), RouteQuestionTests (7) |
| [`src/backend/conversations/tests/test_global_rag_service.py`](src/backend/conversations/tests/test_global_rag_service.py) | 18 tests: BuildGlobalSystemPromptTests (3), BuildGlobalContextTests (6), MultiHubSearchTests (4), RunGlobalRagQueryTests (5) |
| [`src/backend/conversations/tests/test_views_messages.py`](src/backend/conversations/tests/test_views_messages.py) | Added `ConversationMessageViewGlobalRagTests` (7 tests) |
| [`src/backend/conversations/tests/test_serializers.py`](src/backend/conversations/tests/test_serializers.py) | Added hub_metadata tests (3) and mode field tests (4) |
| [`src/backend/documents/tests/test_import_reference_laws.py`](src/backend/documents/tests/test_import_reference_laws.py) | **NEW** — 15 tests: ImportStatsTests (1), ImportCommandTests (14) covering valid JSON, invalid hub_type, missing hub_type, empty documents, empty title/content, dry-run, multiple documents, all hub types, invalid file path, chunking failure, embedding failure, hub_type in metadata, user-id parameter |

## Post-Audit Fixes Applied (2026-05-10)

After a comprehensive code audit, the following 4 issues were identified and fixed:

### P1: Missing test file for import_reference_laws command
- **Created**: [`src/backend/documents/tests/test_import_reference_laws.py`](src/backend/documents/tests/test_import_reference_laws.py) — 15 tests covering all import scenarios

### P2: Missing hub_type in source citations
- **Modified**: [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) — `extract_citations()` now extracts `hub_type` from `chunk["metadata"].get("hub_type")` when present
- **Modified**: [`src/backend/conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) — Added 2 new tests: `test_extracts_hub_type_from_chunk_metadata` and `test_skips_hub_type_when_metadata_missing`

### P3: Missing hub_metadata in streaming SSE done event
- **Modified**: [`src/backend/conversations/views.py`](src/backend/conversations/views.py) — Added `hub_metadata` from `result.get("hub_metadata")` to the SSE `done` event payload

### P4: Source headers lack hub type
- **Modified**: [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) — Source headers now include `Hub: {hub_label}` (e.g., `[Source 1 | Hub: Legislation — قوانین مصوب | Pages 1-3 | قانون: قانون مجازات اسلامی | ماده: 523]`)
- **Modified**: [`src/backend/conversations/tests/test_global_rag_service.py`](src/backend/conversations/tests/test_global_rag_service.py) — Updated `test_global_source_numbering` and `test_includes_legal_context_in_source_header` assertions to match new format

## Test Results

- **74 pytest + Django TestCase tests**: **ALL PASS**
- Breakdown:
  - `test_rag_service.py`: 8 ExtractCitationsTests + others = **ALL PASS**
  - `test_global_rag_service.py`: 18 tests = **ALL PASS**
  - `test_views_messages.py`: 7 GlobalRagTests = **ALL PASS**
  - `test_import_reference_laws.py`: 15 tests = **ALL PASS** (NEW)

## Pre-existing Failures (Unrelated)

The following 4 failures existed before Phase 2a and are not caused by these changes:
1. `test_full_conversation_lifecycle` — `expected 1024 dimensions, not 768` (test fixture uses wrong embedding dim)
2. `test_rag_service_integration` — Same dimension mismatch
3. `test_default_top_k` — Expects `top_k=5` but serializer defaults to `15`
4. `test_post_default_top_k` — Same mismatch in views_query

## Next Steps

1. **Phase 2b**: Frontend integration — Add "Global RAG" mode toggle to ChatPage, update conversationStore, add hub_metadata display
2. **Phase 2c**: Import pipeline — Create seed data scripts for reference laws, judicial precedents, advisory opinions
3. **Phase 2d**: Monitoring & observability — Add per-hub latency tracking, hub_metadata to analytics
