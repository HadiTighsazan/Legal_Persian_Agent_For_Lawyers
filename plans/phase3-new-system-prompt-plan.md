# Phase 3: New System Prompt Integration Plan

> **Objective:** Replace the current `STRATEGIC_ANALYSIS_SYSTEM_PROMPT` and `_build_analysis_prompt()` with a comprehensive Persian legal system prompt that enforces Iranian-law-only reasoning, dual civil/criminal pathway analysis, and a new structured JSON output format.

---

## 1. Impact Analysis

### What Changes

| Component | Change Type | Details |
|-----------|-------------|---------|
| `AnalysisResult` dataclass | **Modify** — add new fields | Add `missing_facts`, `civil_pathway`, `criminal_pathway`, `pathways_relation`, `risk_assessment`, `strategic_recommendation`, `sources_used` |
| `STRATEGIC_ANALYSIS_SYSTEM_PROMPT` | **Replace** entirely | New 9-section Persian prompt |
| `_build_analysis_prompt()` | **Rewrite** | Inject user facts + split legal context by hub into `{{...}}` placeholders |
| `parse_analysis_response()` | **Extend** | Handle new JSON structure |
| `_build_fallback_report()` | **Update** | Build markdown from new fields |
| `StrategicReport` model | **Migrate** — add new DB fields | 7 new columns |
| `_save_strategic_report()` | **Update** | Save new fields |
| `process_message()` | **Update** | Build `raw_report` from new fields for streaming |
| `_research_case()` | **Minor** | Return hub-split context |
| Frontend (future) | Eventually render structured fields | Not in scope now |

### What Stays the Same

| Component | Reason |
|-----------|--------|
| `FactExtractor` | Interview phase is unchanged |
| `_build_fts_keywords()` | FTS keyword generation unchanged |
| `_research_case()` → `multi_hub_search()` | Search pipeline unchanged |
| `_filter_relevant_chunks()` | Relevance filtering unchanged |
| `question_router.py` | Phase 2 untouched |
| `global_rag_service.py` | Phase 2 untouched |

---

## 2. New `AnalysisResult` Dataclass

```python
@dataclass
class AnalysisResult:
    """Result of the strategic analysis LLM call with new structured format."""
    # Core fields (new structure)
    summary: str = ""
    missing_facts: list[str] = field(default_factory=list)
    civil_pathway: str = ""
    criminal_pathway: str = ""
    pathways_relation: str = ""
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    #   risk_assessment format:
    #   {
    #       "strengths": [...],
    #       "weaknesses": [...],
    #       "success_probability": "70 درصد - ..."
    #   }
    strategic_recommendation: str = ""
    sources_used: list[str] = field(default_factory=list)
    
    # Legacy fields (kept for backward compat, populated from new fields)
    success_probability: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    applicable_laws: list[dict[str, Any]] = field(default_factory=list)
    applicable_precedents: list[dict[str, Any]] = field(default_factory=list)
    raw_report: str = ""
```

**Legacy population logic** (in `parse_analysis_response`):
- `success_probability` → parse from `risk_assessment.success_probability` string (e.g., "70 درصد" → 0.7)
- `strengths` → from `risk_assessment.strengths`
- `weaknesses` → from `risk_assessment.weaknesses`
- `risks` → empty (no direct equivalent in new structure)
- `recommendations` → split `strategic_recommendation` into list
- `applicable_laws` → derive from `sources_used` that match legislation
- `applicable_precedents` → derive from `sources_used` that match precedents
- `raw_report` → build from new fields using updated `_build_fallback_report()`

---

## 3. Technical Safeguards

### 3a. Backtick Stripping in JSON Output (Already Handled ✅)

The existing [`_extract_json_from_fence()`](src/backend/conversations/strategist_service.py:1030) already handles LLMs that wrap JSON in markdown code fences:

- **Pattern 1:** Regex `r'```(?:json)?\s*\n(.*?)(?:```|$)'` with `re.DOTALL` — handles ` ``` json ` blocks and truncated responses missing closing fence
- **Pattern 2:** Manual fence prefix stripping (fallback when regex fails)
- **Pattern 3:** Direct JSON object/array detection if no fences present

Then `parse_analysis_response()` cascades through: `json.loads` → `json.loads(strict=False)` → `_repair_json` → regex extraction → `_build_error_result`. No additional changes needed.

### 3b. Mutable Defaults in Django JSONField ⚠️

When adding new `JSONField` fields, **always use callable defaults**, never mutable literals:

```python
# ✅ CORRECT — callable, creates fresh list/dict per row
missing_facts = models.JSONField(default=list, blank=True)
risk_assessment = models.JSONField(default=dict, blank=True)

# ❌ WRONG — mutable, shared across ALL rows (causes bizarre bugs)
missing_facts = models.JSONField(default=[], blank=True)  # DANGER
risk_assessment = models.JSONField(default={}, blank=True)  # DANGER
```

**Rule:** `default=list` and `default=dict` are safe. `default=[]` and `default={}` are forbidden.

---

## 4. New `StrategicReport` Model Fields (Migration Required)

```python
# New fields to add to StrategicReport model:
missing_facts = models.JSONField(default=list, blank=True)
civil_pathway = models.TextField(blank=True, default="")
criminal_pathway = models.TextField(blank=True, default="")
pathways_relation = models.TextField(blank=True, default="")
risk_assessment = models.JSONField(default=dict, blank=True)
strategic_recommendation = models.TextField(blank=True, default="")
sources_used = models.JSONField(default=list, blank=True)
```

Existing fields (`success_probability`, `summary`, `strengths`, etc.) are kept for backward compatibility with existing saved reports.

---

## 4. Prompt Injection Architecture

### Current approach (one combined user prompt):
```
System: [STRATEGIC_ANALYSIS_SYSTEM_PROMPT]
User: ## Case Information\n case_type + facts JSON + case_description + legal_context
```

### New approach (system prompt is self-contained, user prompt just has data):
```
System: [NEW_COMPREHENSIVE_SYSTEM_PROMPT with {{USER_FACTS}}, {{LEGISLATION_CONTEXT}}, {{PRECEDENT_CONTEXT}}, {{ADVISORY_CONTEXT}}]
```

Wait — the system prompt contains `{{USER_FACTS}}`, `{{LEGISLATION_CONTEXT}}` etc. as placeholders. These need to be **injected at runtime** into the system prompt string before sending to the LLM.

### Runtime injection flow:

```python
def _build_analysis_prompt(
    self,
    case_type: str,
    facts: dict[str, Any],
    case_description: str,
    hub_results: dict[str, dict[str, Any]],  # NEW: pass raw hub_results
) -> str:
    """Build the analysis prompt with runtime injection of user facts and context.
    
    The system prompt contains {{PLACEHOLDERS}} that are replaced at runtime
    with actual data. The user message is left minimal — just the task trigger.
    """
    # 1. Format user facts
    user_facts_text = (
        "شرح پرونده: " + case_description + "\n\n"
        + "فکت‌های ساختاریافته:\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
    )
    
    # 2. Format each hub's context (or " no results" if empty)
    legislation_context = self._format_hub_context(
        hub_results.get("legislation", {}).get("chunks", [])
    ) or "هیچ نتیجه‌ای از پایگاه قوانین مصوب بازیابی نشد."
    
    precedent_context = self._format_hub_context(
        hub_results.get("judicial_precedent", {}).get("chunks", [])
    ) or "هیچ نتیجه‌ای از پایگاه آرای قضایی بازیابی نشد."
    
    advisory_context = self._format_hub_context(
        hub_results.get("advisory_opinion", {}).get("chunks", [])
    ) or "هیچ نتیجه‌ای از پایگاه نظریات مشورتی بازیابی نشد."
    
    # 3. Inject into system prompt
    system_prompt = NEW_STRATEGIC_ANALYSIS_SYSTEM_PROMPT.replace(
        "{{USER_FACTS}}", user_facts_text
    ).replace(
        "{{LEGISLATION_CONTEXT}}", legislation_context
    ).replace(
        "{{PRECEDENT_CONTEXT}}", precedent_context
    ).replace(
        "{{ADVISORY_CONTEXT}}", advisory_context
    )
    
    # 4. Return minimal user message (just trigger the analysis)
    return system_prompt  # Used as the system message content
```

The user message can simply be:
```python
"بر اساس اطلاعات فوق، تحلیل راهبردی خود را در قالب JSON ارائه دهید."
```

### Helper method:
```python
def _format_hub_context(self, chunks: list[dict[str, Any]]) -> str:
    """Format chunks from a single hub into a text block with source markers."""
    if not chunks:
        return ""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        content = chunk.get("content", "")
        doc_title = chunk.get("document_title", f"منبع {i}")
        parts.append(f"[{i}] {doc_title}:\n{content}")
    return "\n\n".join(parts)
```

---

## 5. Changes to `_research_case()` — Return Hub Results

The `_research_case()` already returns `hub_results` from `multi_hub_search()`. The `analyze()` method currently passes `legal_context` (combined string) to `_build_analysis_prompt()`. We need to pass `hub_results` instead, so the prompt builder can format each hub separately.

**Change in `analyze()`:**
```python
# OLD: pass legal_context (combined string)
analysis_prompt = self._build_analysis_prompt(
    case_type=case_type,
    facts=facts,
    case_description=case_description,
    legal_context=legal_context,
)

# NEW: pass hub_results (raw dict, split by hub)
system_prompt = self._build_analysis_prompt(
    case_type=case_type,
    facts=facts,
    case_description=case_description,
    hub_results=hub_results,
)
```

---

## 6. Changes to `parse_analysis_response()`

The parsing pipeline already has robust multi-strategy JSON extraction. The main change is handling the new JSON keys.

**New parsing logic** (in `parse_analysis_response()`):

```python
# After successful JSON parse, extract new fields:
summary = data.get("summary", "")
missing_facts = data.get("missing_facts", [])
civil_pathway = data.get("civil_pathway", "")
criminal_pathway = data.get("criminal_pathway", "")
pathways_relation = data.get("pathways_relation", "")
risk_assessment = data.get("risk_assessment", {})
strategic_recommendation = data.get("strategic_recommendation", "")
sources_used = data.get("sources_used", [])

# Populate legacy fields from new structure
success_probability = _parse_probability_from_risk(risk_assessment)
strengths = risk_assessment.get("strengths", []) if isinstance(risk_assessment, dict) else []
weaknesses = risk_assessment.get("weaknesses", []) if isinstance(risk_assessment, dict) else []
risks = []
recommendations = [strategic_recommendation] if strategic_recommendation else []
applicable_laws = _filter_sources_by_type(sources_used, "legislation")
applicable_precedents = _filter_sources_by_type(sources_used, "precedent")
raw_report = _build_fallback_report(...)  # Build from new fields
```

**Helper functions:**
```python
def _parse_probability_from_risk(risk_assessment: dict) -> float:
    """Parse success_probability from risk_assessment string.
    
    Examples: "70 درصد - دعوای مستند به سند رسمی" → 0.7
              "30" → 0.3
    """
    prob_str = risk_assessment.get("success_probability", "") if isinstance(risk_assessment, dict) else ""
    # Extract digits from Persian/Arabic/English numerals
    digits = re.findall(r"[0-9\u06F0-\u06F9]+", prob_str)
    if digits:
        # Convert Persian digits to English
        persian_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        cleaned = digits[0].translate(persian_digits)
        val = float(cleaned)
        if val > 1:
            val /= 100  # "70" → 0.7
        return max(0.0, min(1.0, val))
    return 0.0
```

---

## 7. Update `_save_strategic_report()`

```python
defaults={
    "case_profile": profile,
    # New fields
    "summary": analysis_result.summary,
    "missing_facts": analysis_result.missing_facts,
    "civil_pathway": analysis_result.civil_pathway,
    "criminal_pathway": analysis_result.criminal_pathway,
    "pathways_relation": analysis_result.pathways_relation,
    "risk_assessment": analysis_result.risk_assessment,
    "strategic_recommendation": analysis_result.strategic_recommendation,
    "sources_used": analysis_result.sources_used,
    # Legacy fields (populated from new)
    "success_probability": analysis_result.success_probability,
    "strengths": analysis_result.strengths,
    "weaknesses": analysis_result.weaknesses,
    "risks": analysis_result.risks,
    "recommendations": analysis_result.recommendations,
    "raw_report": analysis_result.raw_report,
}
```

---

## 8. Update `process_message()` "done" Event

The frontend currently receives `analysis` dict with legacy fields. Add new fields alongside:

```python
yield ("done", {
    "content": analysis_result.raw_report,
    "sources": [],
    "token_usage": {...},
    "is_interview": False,
    "case_type": extraction_result.case_type,
    "completeness_score": 1.0,
    # Legacy analysis (for backward compat)
    "analysis": {
        "success_probability": analysis_result.success_probability,
        "summary": analysis_result.summary,
        "strengths": analysis_result.strengths,
        "weaknesses": analysis_result.weaknesses,
        "risks": analysis_result.risks,
        "recommendations": analysis_result.recommendations,
    },
    # New structured fields
    "strategic_analysis": {
        "summary": analysis_result.summary,
        "missing_facts": analysis_result.missing_facts,
        "civil_pathway": analysis_result.civil_pathway,
        "criminal_pathway": analysis_result.criminal_pathway,
        "pathways_relation": analysis_result.pathways_relation,
        "risk_assessment": analysis_result.risk_assessment,
        "strategic_recommendation": analysis_result.strategic_recommendation,
        "sources_used": analysis_result.sources_used,
    },
})
```

---

## 9. Execution Order

| Step | Task | File(s) | Risk |
|------|------|---------|------|
| 1 | Update `AnalysisResult` dataclass with new fields | `strategist_service.py` | Low |
| 2 | Add `_format_hub_context()` helper | `strategist_service.py` | Low |
| 3 | Rewrite `_build_analysis_prompt()` with runtime injection | `strategist_service.py` | Medium |
| 4 | Replace `STRATEGIC_ANALYSIS_SYSTEM_PROMPT` with new comprehensive Persian text | `strategist_service.py` | Medium |
| 5 | Update `parse_analysis_response()` and add `_parse_probability_from_risk()` | `strategist_service.py` | Medium |
| 6 | Update `_build_fallback_report()` for new structure | `strategist_service.py` | Low |
| 7 | Update `analyze()` to pass `hub_results` instead of `legal_context` | `strategist_service.py` | Low |
| 8 | Create DB migration for new `StrategicReport` fields | `models.py` + migration | High — run on data |
| 9 | Update `_save_strategic_report()` | `strategist_service.py` | Low |
| 10 | Update `process_message()` "done" event | `strategist_service.py` | Low |
| 11 | Run tests and verify | test files | — |
| 12 | Update `docs/references/database-schema.md` | docs | — |

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| DB migration on production data | All new fields have `default` and `blank=True` — existing rows get empty values |
| LLM doesn't follow new JSON format | The existing multi-strategy parsing pipeline (`parse_analysis_response`) handles malformed JSON gracefully — falls back to regex extraction + `_build_fallback_report` |
| New system prompt too long | Keep max_tokens at 8192. Monitor actual token usage. |
| Persian placeholder injection fails | Use `str.replace()` with exact match — test with edge cases |
| Frontend relies on old `analysis` structure | Legacy fields are still populated from new data — no frontend breakage |
