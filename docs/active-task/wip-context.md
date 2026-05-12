# WIP Context — Phase 2b Implementation (Global RAG Full)

## Status: ✅ COMPLETED (2026-05-12)

## Summary

Implemented Phase 2b (Global RAG Full) — transforming the Global RAG pipeline from a single-pass LLM synthesis (Phase 2a) to a per-hub partial answer + synthesis architecture with conflict detection. All 38 tests pass.

---

## What Was Built

### Step 1: Per-Hub Specialized System Prompts

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py)

Three new functions:

- **`build_hub_system_prompt(hub_type)`** (line 285): Returns a specialized system prompt for each hub:
  - `legislation`: Focuses on articles, clauses, legal materials, exact article numbers
  - `judicial_precedent`: Focuses on judgment numbers, court names, dates, binding precedents
  - `advisory_opinion`: Focuses on opinion numbers, issuing authorities, advisory nature
  - Raises `ValueError` for unknown hub types

- **`build_synthesis_system_prompt()`** (line 356): Returns the synthesis prompt with:
  - Conflict detection instructions (`[Conflict]` marker)
  - Legal hierarchy resolution (Legislation > Judicial Precedent > Advisory Opinions)
  - Persian answer instruction

- **`build_global_system_prompt()`** (line 623): Kept as legacy/deprecated for backward compatibility with Phase 2a

### Step 2: Per-Hub Partial Answer Generation

**Function:** `generate_hub_partial_answer(hub_type, question, chunks)` (line 415)

- If no chunks → returns immediately with Persian "no info" message (no LLM call)
- Builds single-hub context via `build_global_context()`
- Calls chat provider with hub-specific system prompt
- Returns `{content, token_usage, error}`
- Catches exceptions gracefully (returns error in dict, doesn't crash pipeline)

### Step 3: Answer Synthesis with Conflict Detection

**Function:** `synthesize_answers(question, partial_answers)` (line 518)

- Builds synthesis context from all partial answers
- Calls chat provider with synthesis prompt (conflict detection + legal hierarchy)
- Returns `{content, token_usage, error}`
- Catches exceptions gracefully

### Step 4: Refactored `run_global_rag_query()` (line 676)

Pipeline now executes 6 steps:
1. **Route** the question to relevant hubs
2. **Search** each relevant hub
3. **Generate** per-hub partial answers (up to 3 LLM calls)
4. **Synthesize** partial answers (1 LLM call)
5. **Extract** citations
6. **Return** result with `partial_answers` key

Total: up to **4 LLM calls** per query (3 per-hub + 1 synthesis).

Token usage is accumulated across all LLM calls.

If synthesis returns an error (caught internally by `synthesize_answers()`), `run_global_rag_query()` raises `GlobalRAGServiceException`.

### Step 5: Updated `hub_metadata`

Each hub in `hub_metadata` now includes:
- `partial_answer` (str): The partial answer text
- `partial_answer_token_usage` (dict): Token usage for that hub's LLM call
- `partial_answer_error` (str | None): Error message if the LLM call failed

### Step 6: API Response — No Serializer Changes Needed

The `MessageSerializer` already exposes `hub_metadata` as a read-only `JSONField`. The `partial_answers` dict is nested inside the response (not in `hub_metadata`), so no serializer changes were required.

### Step 7: Tests — 38 Total (20 New + 18 Existing)

**File:** [`src/backend/conversations/tests/test_global_rag_service.py`](src/backend/conversations/tests/test_global_rag_service.py)

New test classes:
| Class | Tests | Description |
|---|---|---|
| `BuildHubSystemPromptTests` | 5 | Each hub prompt has specialized instructions, raises ValueError for unknown hub, all contain base instructions |
| `BuildSynthesisSystemPromptTests` | 4 | Conflict detection, legal hierarchy, synthesis instructions, Persian answer instruction |
| `GenerateHubPartialAnswerTests` | 4 | Generation with chunks, empty chunks (no LLM call), LLM error handling, correct system prompt per hub type |
| `SynthesizeAnswersTests` | 4 | Merging partial answers, conflict detection, single hub, all hubs empty |

Updated `RunGlobalRagQueryTests` with 7 tests (3 updated from Phase 2a + 4 new):
- `test_full_pipeline_returns_expected_keys` — checks `partial_answers` key + token accumulation
- `test_partial_answers_included_in_hub_metadata` — checks per-hub `partial_answer` fields
- `test_partial_answers_returned_in_response` — checks `partial_answers` dict structure
- `test_token_usage_includes_all_llm_calls` — checks accumulated tokens across 3 calls (2 per-hub + 1 synthesis)
- `test_passes_conversation_history` — backward compat check
- `test_route_question_failure_raises_exception` — unchanged from Phase 2a
- `test_synthesis_failure_raises_exception` — checks synthesis error raises exception
- `test_backward_compatible_response_format` — checks Phase 2a keys still present

### Step 8: Test Results — ✅ ALL 38 PASS

```
38 passed in 3.66s
```

### Step 9: Updated Reference Documentation

- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md): This file — recorded Phase 2b completion
- [`docs/references/api-registry.md`](docs/references/api-registry.md): Updated Global RAG response example to include `partial_answers` and updated `hub_metadata` structure

---

## Files Modified

| File | Description |
|---|---|
| [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) | Added `build_hub_system_prompt()`, `build_synthesis_system_prompt()`, `generate_hub_partial_answer()`, `synthesize_answers()`. Refactored `run_global_rag_query()` for Phase 2b. Added synthesis error check. |
| [`src/backend/conversations/tests/test_global_rag_service.py`](src/backend/conversations/tests/test_global_rag_service.py) | Added 20 new tests across 4 new test classes. Updated `RunGlobalRagQueryTests` with 4 new tests. |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | This file — recorded Phase 2b completion |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Updated Global RAG response example with `partial_answers` and updated `hub_metadata` structure |

## Files Created

| File | Description |
|---|---|
| [`plans/plan-phase2b-implementation.md`](plans/plan-phase2b-implementation.md) | Detailed implementation plan for Phase 2b |

## Next Steps

1. **End-to-end verification**: Send a Global RAG query via the API and verify the new `partial_answers` field in the response
2. **Phase 3 planning**: Streaming support for Global RAG, frontend enhancements
