# Implementation Plan: Phase 3 & 4 — Interactive Strategist + Action Engine

> **Goal:** Transform the system from a passive Q&A tool into an active legal assistant that can strategize, analyze case strength, and generate legal documents — all through conversation, without requiring legible uploaded documents.

---

## Overview

### Phase 3: Interactive Strategist (استراتژیست تعاملی)
A guided interview flow where the LLM drives the conversation to gather case facts, then produces a structured strategic analysis with success probability, risks, and recommendations — all grounded in the existing legal database.

### Phase 4: Action Engine (موتور اقدام)
A legal action planning and document drafting tool. The user describes their legal objective, the system researches the legal pathway, generates a step-by-step roadmap, and drafts targeted legal texts (petitions, notices, clauses).

### Key UX Principle
Both phases are **separate frontend destinations** with their own:
- Sidebar navigation entries
- Route paths
- Page components
- Conversation lists (filtered by mode)

This mirrors the existing pattern where Document Chat and Legal Research are separate pages.

---

## Phase 3: Interactive Strategist — Detailed Plan

### 3.1 Backend: New Service (`src/backend/conversations/strategist_service.py`)

**Purpose:** Orchestrate the guided interview → research → analysis pipeline.

#### Core Components

| Component | Description |
|-----------|-------------|
| `StrategistService` | Main orchestrator class with methods for each pipeline phase |
| `FactExtractor` | LLM-powered extraction of structured facts from conversation |
| `CompletenessChecker` | Identifies missing critical facts based on case type |
| `StrategicAnalyzer` | Evaluates success probability, strengths, weaknesses |
| `ReportGenerator` | Produces structured Persian strategic report |

#### Pipeline Flow

```
1. receive_case_description(user_input, conversation_history)
   → LLM analyzes input, identifies case type (contract, family, criminal, etc.)
   → Returns structured case profile with known facts and gaps

2. generate_next_question(case_profile, conversation_history)
   → LLM determines the most important missing fact
   → Returns a targeted question in Persian

3. check_readiness(case_profile)
   → If enough facts gathered → proceed to analysis
   → If gaps remain → return to step 2

4. run_strategic_analysis(case_profile)
   → Query all 3 legal hubs via multi_hub_search()
   → LLM analyzes facts against retrieved laws/precedents
   → Generate success probability, risk assessment, recommendations

5. generate_report(analysis_result)
   → Format as structured Persian report with sections
   → Include citations to specific laws and precedents
```

#### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/conversations/strategist/analyze` | Send case description, get next question or final analysis |
| `POST` | `/conversations/{id}/strategist/answer` | Answer a question from the strategist |
| `GET` | `/conversations/{id}/strategist/report` | Retrieve the latest strategic report |

**Alternative (simpler):** Extend existing message endpoints with `mode: "strategist"` — the existing streaming infrastructure handles the conversation, and the strategist service is called instead of `run_global_rag_query()`.

### 3.2 Backend: Data Model Changes

#### New Field on `Conversation`

```python
# Add to Conversation model
mode = models.CharField(
    max_length=20,
    choices=[
        ("local_rag", "Local RAG"),
        ("global_rag", "Global RAG / Legal Research"),
        ("strategist", "Interactive Strategist"),
        ("action_engine", "Action Engine"),
    ],
    default="global_rag",
    null=True,  # Existing conversations get null → treated as global_rag
)
```

This enables:
- Filtering conversations by mode in the sidebar
- Routing messages to the correct service
- Displaying mode-specific UI in the frontend

#### New Models

```python
class CaseProfile(models.Model):
    """Structured facts extracted from a strategist conversation."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name="case_profile")
    case_type = models.CharField(max_length=100)  # e.g., "contract_dispute", "family_law", "criminal"
    facts = models.JSONField(default=dict)  # Structured facts: {parties, claims, evidence, timeline, ...}
    completeness_score = models.FloatField(default=0.0)  # 0.0 to 1.0
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class StrategicReport(models.Model):
    """Generated strategic analysis report."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name="strategic_report")
    case_profile = models.ForeignKey(CaseProfile, on_delete=models.CASCADE)
    success_probability = models.FloatField()  # 0.0 to 1.0
    summary = models.TextField()
    strengths = models.JSONField(default=list)
    weaknesses = models.JSONField(default=list)
    risks = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    applicable_laws = models.JSONField(default=list)  # [{title, articles, citations}]
    applicable_precedents = models.JSONField(default=list)  # [{title, number, summary}]
    raw_report = models.TextField()  # Full Persian markdown report
    created_at = models.DateTimeField(auto_now_add=True)
```

### 3.3 Backend: Serializer Changes

Extend `AskQuestionSerializer.MODE_CHOICES`:

```python
MODE_CHOICES = [
    ("local_rag", "Local RAG — search within the conversation's document"),
    ("global_rag", "Global RAG — search across all legal knowledge hubs"),
    ("strategist", "Interactive Strategist — guided case analysis"),
    ("action_engine", "Action Engine — legal roadmap and document drafting"),
]
```

### 3.4 Backend: View Changes

In [`src/backend/conversations/views.py`](../src/backend/conversations/views.py):

- Extend `ConversationMessageView.post()` and `ConversationMessageStreamView.post()` to handle `mode="strategist"` and `mode="action_engine"`
- Add new mode routing similar to existing `if mode == "global_rag":` / `else:` blocks
- Strategist mode calls `strategist_service.process_message()` instead of RAG services
- Action Engine mode calls `action_engine_service.process_message()`

### 3.5 Frontend: New Page — `StrategistPage`

**File:** [`src/frontend/src/pages/StrategistPage.tsx`](../src/frontend/src/pages/StrategistPage.tsx)

**Pattern:** Follow the exact same pattern as [`GlobalRagChatPage.tsx`](../src/frontend/src/pages/GlobalRagChatPage.tsx) — full-height layout outside AppShell, with conversation sidebar.

**Key Differences from GlobalRagChatPage:**
- Uses `mode="strategist"` when calling the messages API
- Empty state shows a prompt asking the user to describe their case
- ChatWindow renders with strategist-specific styling (e.g., structured report sections)
- May include a "Generate Report" button that triggers the final analysis

**Route:** `/strategist` and `/strategist/:conversationId`

### 3.6 Frontend: New Page — `ActionEnginePage`

**File:** [`src/frontend/src/pages/ActionEnginePage.tsx`](../src/frontend/src/pages/ActionEnginePage.tsx)

**Pattern:** Same as `GlobalRagChatPage.tsx` — full-height layout, conversation sidebar.

**Key Differences:**
- Uses `mode="action_engine"` when calling the messages API
- Empty state prompts the user to describe their legal objective
- Renders drafted documents with special formatting (code blocks for legal text)
- May include export/copy buttons for generated legal texts

**Route:** `/action-engine` and `/action-engine/:conversationId`

### 3.7 Frontend: Sidebar Updates

**File:** [`src/frontend/src/components/layout/Sidebar.tsx`](../src/frontend/src/components/layout/Sidebar.tsx)

Add two new nav items:

```typescript
const navItems: NavItem[] = [
  // ... existing items ...
  {
    label: 'Strategist',
    icon: <Scale className="h-5 w-5" />,  // or BrainCircuit, GitCompare
    href: '/strategist',
  },
  {
    label: 'Action Engine',
    icon: <FilePen className="h-5 w-5" />,  // or FileOutput, PenTool
    href: '/action-engine',
  },
];
```

Update active state detection:

```typescript
const isActive =
  item.href === '/documents'
    ? location.pathname.startsWith('/documents')
    : item.href === '/legal-research'
    ? location.pathname.startsWith('/legal-research')
    : item.href === '/strategist'
    ? location.pathname.startsWith('/strategist')
    : item.href === '/action-engine'
    ? location.pathname.startsWith('/action-engine')
    : location.pathname === item.href;
```

### 3.8 Frontend: Router Updates

**File:** [`src/frontend/src/App.tsx`](../src/frontend/src/App.tsx)

Add new routes (outside AppShell, same pattern as legal-research):

```typescript
// Strategist routes — outside AppShell
{ path: '/strategist', element: <StrategistPage /> },
{ path: '/strategist/:conversationId', element: <StrategistPage /> },
// Action Engine routes — outside AppShell
{ path: '/action-engine', element: <ActionEnginePage /> },
{ path: '/action-engine/:conversationId', element: <ActionEnginePage /> },
```

### 3.9 Frontend: Dashboard Updates

**File:** [`src/frontend/src/pages/DashboardPage.tsx`](../src/frontend/src/pages/DashboardPage.tsx)

Add two new quick-action cards:

```tsx
// Strategist Card
<Card onClick={() => navigate('/strategist')}>
  <CardHeader>
    <CardTitle>Interactive Strategist</CardTitle>
    <Scale className="h-5 w-5 text-primary" />
  </CardHeader>
  <CardContent>
    <p>Describe your case and get a strategic analysis with success probability.</p>
    <Button>Start Analysis</Button>
  </CardContent>
</Card>

// Action Engine Card
<Card onClick={() => navigate('/action-engine')}>
  <CardHeader>
    <CardTitle>Action Engine</CardTitle>
    <FilePen className="h-5 w-5 text-primary" />
  </CardHeader>
  <CardContent>
    <p>Get a step-by-step legal roadmap and drafted legal documents.</p>
    <Button>Start Drafting</Button>
  </CardContent>
</Card>
```

### 3.10 Frontend: ConversationSidebar Updates

**File:** [`src/frontend/src/components/chat/ConversationSidebar.tsx`](../src/frontend/src/components/chat/ConversationSidebar.tsx)

The sidebar already lists conversations. We need to:
- Add a `mode` filter prop to show only conversations matching the current page's mode
- Or pass a `mode` parameter to the API to filter conversations server-side

**API Change:** Add `?mode=strategist` query parameter to `GET /conversations/` to filter by conversation mode.

---

## Phase 4: Action Engine — Detailed Plan

### 4.1 Backend: New Service (`src/backend/conversations/action_engine_service.py`)

**Purpose:** Orchestrate the objective clarification → research → roadmap → drafting pipeline.

#### Core Components

| Component | Description |
|-----------|-------------|
| `ActionEngineService` | Main orchestrator class |
| `ObjectiveClarifier` | LLM-driven interview to clarify the user's legal goal |
| `ProceduralResearcher` | Queries all 3 hubs for procedural requirements |
| `RoadmapGenerator` | Generates step-by-step legal action plan |
| `LegalDrafter` | Drafts specific legal texts with citations |

#### Pipeline Flow

```
1. receive_objective(user_input, conversation_history)
   → LLM identifies document type needed (petition, notice, contract clause)
   → Returns structured objective profile

2. generate_clarifying_question(objective_profile)
   → LLM asks about missing details (parties, amounts, deadlines)
   → Returns targeted question

3. check_readiness(objective_profile)
   → If enough info → proceed to research + drafting
   → If gaps remain → return to step 2

4. research_and_draft(objective_profile)
   → Query all 3 legal hubs for relevant laws and precedents
   → Generate procedural roadmap
   → Draft legal text with citations
   → Return structured output
```

### 4.2 Backend: Data Model Changes

```python
class ActionPlan(models.Model):
    """Generated legal action roadmap."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name="action_plan")
    objective_type = models.CharField(max_length=100)  # e.g., "file_lawsuit", "draft_contract", "send_notice"
    steps = models.JSONField(default=list)  # Ordered list of steps with descriptions
    required_documents = models.JSONField(default=list)
    estimated_timeline = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class LegalDraft(models.Model):
    """Drafted legal text."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="legal_drafts")
    draft_type = models.CharField(max_length=100)  # e.g., "petition", "legal_notice", "contract_clause"
    title = models.CharField(max_length=500)
    content = models.TextField()  # The drafted legal text
    citations = models.JSONField(default=list)  # Supporting law/precedent citations
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 4.3 Frontend: Same pattern as Phase 3

- New page at `/action-engine` and `/action-engine/:conversationId`
- Same layout pattern as `GlobalRagChatPage.tsx`
- Special rendering for drafted legal texts (monospace, numbered paragraphs, citation footnotes)

---

## Implementation Order

### Step 1: Data Model Changes (Backend)
1. Add `mode` field to `Conversation` model
2. Create `CaseProfile` and `StrategicReport` models
3. Create `ActionPlan` and `LegalDraft` models
4. Run migrations
5. Update [`docs/references/database-schema.md`](../docs/references/database-schema.md)

### Step 2: Backend Services
1. Create [`src/backend/conversations/strategist_service.py`](../src/backend/conversations/strategist_service.py)
   - Implement `StrategistService` class
   - Implement fact extraction, completeness checking, strategic analysis
   - Write unit tests
2. Create [`src/backend/conversations/action_engine_service.py`](../src/backend/conversations/action_engine_service.py)
   - Implement `ActionEngineService` class
   - Implement objective clarification, roadmap generation, legal drafting
   - Write unit tests

### Step 3: Backend API Updates
1. Extend `AskQuestionSerializer.MODE_CHOICES` with `"strategist"` and `"action_engine"`
2. Update `ConversationMessageView` and `ConversationMessageStreamView` to route new modes
3. Add `?mode=` filter to `GET /conversations/`
4. Write integration tests

### Step 4: Frontend — Strategist Page
1. Create [`src/frontend/src/pages/StrategistPage.tsx`](../src/frontend/src/pages/StrategistPage.tsx)
2. Create empty state component for strategist
3. Add route to [`src/frontend/src/App.tsx`](../src/frontend/src/App.tsx)
4. Add sidebar nav item
5. Add dashboard card

### Step 5: Frontend — Action Engine Page
1. Create [`src/frontend/src/pages/ActionEnginePage.tsx`](../src/frontend/src/pages/ActionEnginePage.tsx)
2. Create empty state component for action engine
3. Add route to [`src/frontend/src/App.tsx`](../src/frontend/src/App.tsx)
4. Add sidebar nav item
5. Add dashboard card

### Step 6: Frontend — ConversationSidebar Filtering
1. Update `ConversationSidebar` to accept and pass `mode` filter
2. Update API calls to include `?mode=` parameter
3. Ensure each page only shows its own conversation type

### Step 7: Integration & Testing
1. End-to-end flow testing for Strategist
2. End-to-end flow testing for Action Engine
3. Verify backward compatibility (existing Local RAG and Global RAG still work)
4. Update [`docs/references/api-registry.md`](../docs/references/api-registry.md)
5. Update [`docs/active-task/wip-context.md`](../docs/active-task/wip-context.md)

---

## Key Design Decisions

### Decision 1: New mode field on Conversation vs. separate model
**Chosen:** Add `mode` field to existing `Conversation` model.
**Rationale:** Reuses all existing conversation infrastructure (CRUD, messaging, streaming). Avoids duplicating the entire conversation system. The mode field enables filtering and routing without schema duplication.

### Decision 2: New service files vs. extending existing rag_service.py
**Chosen:** New service files (`strategist_service.py`, `action_engine_service.py`).
**Rationale:** The strategist and action engine have fundamentally different flows from RAG (they are interview-driven, not query-driven). Keeping them separate maintains the Single Responsibility Principle and prevents the RAG service from becoming a monolith.

### Decision 3: Separate frontend pages vs. mode-switching within one page
**Chosen:** Separate pages with dedicated routes.
**Rationale:** The user explicitly requested separate frontend destinations (like Document Chat vs. Legal Research). Each feature has a distinct empty state, interaction pattern, and visual presentation. Separate pages provide clear navigation and mental models.

### Decision 4: Streaming vs. non-streaming for strategist/action engine
**Chosen:** Use the existing streaming infrastructure (`ConversationMessageStreamView`) for both new modes.
**Rationale:** The strategist interview flow benefits from streaming (user sees questions appearing). The action engine can stream roadmap steps and drafted text. Reuses the proven SSE pattern.

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM hallucinates legal analysis | High | All analysis must cite specific laws/precedents from the database. Implement citation verification step. |
| Interview flow feels unnatural | Medium | Design prompts carefully. Use few-shot examples. Allow users to skip questions. |
| Conversation mode migration | Low | New `mode` field defaults to `null` (treated as `global_rag`). Existing conversations unaffected. |
| Frontend complexity | Medium | Reuse existing `ChatWindow` and `ConversationSidebar` components. Only create new page shells. |
| Persian legal drafting quality | Medium | Use specialized prompts with examples of Persian legal writing. Include formatting guidelines. |

---

## Files to Modify

### Backend
- [`src/backend/conversations/models.py`](../src/backend/conversations/models.py) — Add `mode` field, new models
- [`src/backend/conversations/serializers.py`](../src/backend/conversations/serializers.py) — Extend `MODE_CHOICES`
- [`src/backend/conversations/views.py`](../src/backend/conversations/views.py) — Route new modes
- [`src/backend/conversations/urls.py`](../src/backend/conversations/urls.py) — Add mode filter parameter

### Backend — New Files
- [`src/backend/conversations/strategist_service.py`](../src/backend/conversations/strategist_service.py)
- [`src/backend/conversations/action_engine_service.py`](../src/backend/conversations/action_engine_service.py)

### Frontend — New Files
- [`src/frontend/src/pages/StrategistPage.tsx`](../src/frontend/src/pages/StrategistPage.tsx)
- [`src/frontend/src/pages/ActionEnginePage.tsx`](../src/frontend/src/pages/ActionEnginePage.tsx)

### Frontend — Modified Files
- [`src/frontend/src/App.tsx`](../src/frontend/src/App.tsx) — Add routes
- [`src/frontend/src/components/layout/Sidebar.tsx`](../src/frontend/src/components/layout/Sidebar.tsx) — Add nav items
- [`src/frontend/src/pages/DashboardPage.tsx`](../src/frontend/src/pages/DashboardPage.tsx) — Add cards
- [`src/frontend/src/components/chat/ConversationSidebar.tsx`](../src/frontend/src/components/chat/ConversationSidebar.tsx) — Add mode filtering

### Documentation
- [`docs/roadmap.md`](../docs/roadmap.md) — Already updated
- [`docs/references/database-schema.md`](../docs/references/database-schema.md) — Update after model changes
- [`docs/references/api-registry.md`](../docs/references/api-registry.md) — Update after API changes
- [`docs/active-task/wip-context.md`](../docs/active-task/wip-context.md) — Update throughout
