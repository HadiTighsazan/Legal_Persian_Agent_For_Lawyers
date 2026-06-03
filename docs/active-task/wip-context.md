# WIP Context — Phase 3 Task 5: Strategist Service Logic (Real AI Brain)

## What Was Just Completed

### Task 5: Strategist Service Logic — Replace Mock with Real AI Brain

Implemented the full real AI brain for the `StrategistService` in [`src/backend/conversations/strategist_service.py`](../../src/backend/conversations/strategist_service.py), replacing the previously non-existent `StrategistService` class. The three core components (`FactExtractor`, `CompletenessChecker`, `StrategicAnalyzer`) were already implemented with real LLM calls — the missing piece was the orchestrator `StrategistService` class and the truncated `_build_fallback_report` method.

### Changes Made

#### 1. [`src/backend/conversations/strategist_service.py`](../../src/backend/conversations/strategist_service.py)

**Fixed:** `_build_fallback_report` method (was truncated at line 967, cutting off mid-Persian text). Now fully generates a complete Persian markdown report with all sections:
- خلاصه (Summary)
- احتمال موفقیت (Success Probability)
- نقاط قوت (Strengths)
- نقاط ضعف (Weaknesses)
- ریسک‌ها (Risks)
- توصیه‌ها (Recommendations)
- قوانین مرتبط (Applicable Laws)
- رویه‌های قضایی مرتبط (Applicable Precedents)

**Added:** `StrategistService` class — the main orchestrator with:

- **`process_message(message, conversation_history, conversation_id)`** — Generator that yields `(event_type, data)` tuples for streaming SSE responses. Implements the full pipeline:

  1. **Fact Extraction** — Calls `FactExtractor.extract()` with the user message, conversation history, and any existing `CaseProfile` facts. Persists/updates the `CaseProfile` model.
  
  2. **Readiness Check** — If `is_ready=False`, uses the `next_question` from extraction (or runs `CompletenessChecker` for a more targeted question) and yields it as a token, then yields `done` with `is_interview=True`.
  
  3. **Strategic Analysis** — When ready, calls `StrategicAnalyzer.analyze()` which routes the case, runs `multi_hub_search()` across all 3 legal hubs, builds legal context via `build_global_context()`, and calls the LLM for the full analysis.
  
  4. **Report Persistence** — Saves the `StrategicReport` model with all analysis fields.
  
  5. **Streaming Output** — Yields the report in 50-char chunks for smooth streaming, then yields `done` with full analysis data.

- **`_save_case_profile()`** — Creates or updates `CaseProfile` via `update_or_create`.
- **`_save_strategic_report()`** — Creates `CaseProfile` (if needed) and `StrategicReport` records.

**Module-level singleton:** `strategist_service = StrategistService()` — already imported by views.py.

#### 2. [`src/backend/conversations/views.py`](../../src/backend/conversations/views.py)

Updated both `ConversationMessageView.post()` and `ConversationMessageStreamView.post()` to pass `conversation_id=str(conversation.id)` to `strategist_service.process_message()`, enabling the service to persist `CaseProfile` and `StrategicReport` models.

Updated the streaming view to also forward `progress` events from the strategist service to the frontend (previously only handled `token` and `done` events).

### Pipeline Flow (Real AI)

```
User Message
    │
    ▼
┌─────────────────────────────┐
│  FactExtractor.extract()    │  ← LLM call (600 tokens)
│  - Identifies case type     │
│  - Extracts structured facts│
│  - Estimates completeness   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Completeness Check         │
│  - score >= 0.7?            │
└──────┬──────────┬───────────┘
       │          │
    No ▼          ▼ Yes
  (Question)   ┌─────────────────────────────┐
               │  StrategicAnalyzer.analyze()│
               │  1. route_question()        │  ← LLM call
               │  2. multi_hub_search()      │  ← Parallel DB + Embedding
               │  3. build_global_context()  │
               │  4. LLM analysis            │  ← LLM call (2000 tokens)
               │  5. Parse + fallback report │
               └──────────┬──────────────────┘
                          │
                          ▼
               ┌─────────────────────────────┐
               │  Persist StrategicReport    │
               │  Stream report tokens       │
               └─────────────────────────────┘
```

### Verification

- Python AST parse: ✅ Both files parse without syntax errors
- Django import test: ✅ `strategist_service` imports correctly, has all expected attributes
- Existing tests: ✅ All 18 message view tests pass, all model/serializer tests pass
- Pre-existing failure: `test_full_conversation_lifecycle` in integration tests was already failing before these changes (assertion on `sources` count)

### 🔧 Fix Applied: `test_full_conversation_lifecycle` — Wrong RAG mode

**Root Cause:** The test was written when the default mode was `local_rag`, but the serializer default was later changed to `"global_rag"`. The test didn't pass `"mode"` in its POST data, so it routed to the unmocked `run_global_rag_query()` instead of the mocked `run_rag_query()`, causing real LLM calls and empty sources.

**Fix:** Added `"mode": "local_rag"` to both POST requests in the test (lines 122 and 152), ensuring the requests route to the mocked `run_rag_query()`.

**Files changed:**
- [`src/backend/conversations/tests/test_integration.py`](../../src/backend/conversations/tests/test_integration.py) — Lines 122 and 152

## Current State

The Strategist backend is now fully implemented with real AI:

- **FactExtractor** — Uses LLM to extract structured case facts from conversation
- **CompletenessChecker** — Uses LLM to evaluate fact completeness and generate targeted questions
- **StrategicAnalyzer** — Routes cases to legal hubs, searches laws/precedents, runs LLM analysis
- **StrategistService** — Orchestrates the full pipeline with streaming output and DB persistence
- **Views** — Both non-streaming and streaming endpoints pass `conversation_id` for persistence
- **Models** — `CaseProfile` and `StrategicReport` are created/updated throughout the pipeline

## Next Steps

1. **Test the end-to-end flow** — Create a strategist conversation via the frontend, send a case description, verify:
   - The LLM extracts facts and asks follow-up questions
   - After enough facts, the strategic analysis runs with legal research
   - The report streams back properly
   - `CaseProfile` and `StrategicReport` are persisted in the database

2. **Phase 4: Action Engine** — Implement `action_engine_service.py` following the same pattern
