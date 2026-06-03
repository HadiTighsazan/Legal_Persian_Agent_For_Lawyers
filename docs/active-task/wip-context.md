# WIP Context — Phase 3 Task 1: Database Setup (Interactive Strategist)

## What Was Just Completed

### Task 1: Database Setup for Interactive Strategist

Added the `mode` field to the `Conversation` model and created the `CaseProfile` and `StrategicReport` models. Migrated the database successfully.

### Changes Made

#### 1. [`src/backend/conversations/models.py`](../../src/backend/conversations/models.py)

**Added `mode` field to `Conversation`:**
```python
mode = models.CharField(
    max_length=20,
    choices=[
        ("local_rag", "Local RAG"),
        ("global_rag", "Global RAG / Legal Research"),
        ("strategist", "Interactive Strategist"),
        ("action_engine", "Action Engine"),
    ],
    default="global_rag",
    null=True,
    help_text="Conversation mode: local_rag, global_rag, strategist, or action_engine. "
              "Null defaults to global_rag for backward compatibility.",
)
```
- Added `models.Index(fields=['mode'])` to `Conversation.Meta.indexes`
- Existing conversations get `null` → treated as `global_rag` (backward compatible)

**Added `CaseProfile` model:**
- `id` — UUID primary key
- `conversation` — OneToOneField to `Conversation` (related_name="case_profile")
- `case_type` — CharField(max_length=100), e.g., "contract_dispute", "family_law", "criminal"
- `facts` — JSONField(default=dict), structured facts: {parties, claims, evidence, timeline, ...}
- `completeness_score` — FloatField(default=0.0), 0.0 to 1.0
- `is_complete` — BooleanField(default=False)
- `created_at`, `updated_at` — auto timestamps
- Indexes on `conversation` and `case_type`

**Added `StrategicReport` model:**
- `id` — UUID primary key
- `conversation` — OneToOneField to `Conversation` (related_name="strategic_report")
- `case_profile` — ForeignKey to `CaseProfile`
- `success_probability` — FloatField, 0.0 to 1.0
- `summary` — TextField
- `strengths`, `weaknesses`, `risks`, `recommendations` — JSONField(default=list)
- `applicable_laws` — JSONField(default=list), [{title, articles, citations}]
- `applicable_precedents` — JSONField(default=list), [{title, number, summary}]
- `raw_report` — TextField (full Persian markdown report)
- `created_at` — auto timestamp
- Indexes on `conversation` and `case_profile`

**Did NOT add:** `ActionPlan` or `LegalDraft` models (deferred to Phase 4).

#### 2. Migration

- **File:** `src/backend/conversations/migrations/0004_add_mode_caseprofile_strategicreport.py`
- **Created:** `docker-compose exec backend python manage.py makemigrations conversations --name add_mode_caseprofile_strategicreport`
- **Applied:** `docker-compose exec backend python manage.py migrate conversations` → OK

#### 3. [`docs/references/database-schema.md`](../../docs/references/database-schema.md)

- Added `mode` column to `conversations` table documentation
- Added `idx_conversations_mode` index
- Added `case_profiles` table (section 9)
- Added `strategic_reports` table (section 10)
- Added migration 0004 documentation under Migrations section

## Current State

Database is migrated and ready. The `mode` field, `CaseProfile`, and `StrategicReport` models are in place.

## Next Step

Proceed to **Task 2: Backend Services** — Create `src/backend/conversations/strategist_service.py` with the `StrategistService` class, implementing the guided interview → research → analysis pipeline.
