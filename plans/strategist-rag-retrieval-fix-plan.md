# Strategist RAG Retrieval Fix Plan

## Root Cause Analysis

After tracing the full pipeline from user input to final report, I've identified **4 root causes** that cascade into the generic/irrelevant analysis the user observed.

---

### Root Cause #1 (PRIMARY): `_build_case_description` produces a JSON dump, not a search-optimized description

**File:** [`src/backend/conversations/strategist_service.py:757`](src/backend/conversations/strategist_service.py:757)

The current implementation:

```python
def _build_case_description(self, case_type, facts):
    parts = [f"Case Type: {case_type}"]
    parts.append("Facts:\n" + json.dumps(facts, ensure_ascii=False, indent=2))
    return "\n\n".join(parts)
```

This produces:
```
Case Type: contract_dispute

Facts:
{
  "parties": {"موجر": "کاربر", "مستاجر": "نامشخص"},
  "claims": "عدم پرداخت اجاره و تخلیه",
  "amount": 60000000,
  ...
}
```

**Why this fails:** The [`route_question()`](src/backend/conversations/question_router.py:173) function receives this JSON blob and tries to generate search queries. The router's [`SYSTEM_PROMPT`](src/backend/conversations/question_router.py:70) expects a natural language legal question (e.g., _"مجازات کلاهبرداری طبق قانون چقدر است؟"_). Instead, it gets a JSON dump with English labels. The LLM gets confused and generates poor FTS/vector queries, or the router fails entirely and falls back to [`_all_hubs_fallback()`](src/backend/conversations/question_router.py:521) which uses the raw JSON blob as the search query for all hubs.

**Impact:** The embedding search compares the JSON blob's embedding against legal document embeddings. Since legal documents are written in fluent Persian legal language, the similarity scores are poor, and irrelevant chunks (like Article 650 of the Islamic Penal Code about false testimony) may rank higher than they should.

---

### Root Cause #2: No chunk relevance validation before passing to LLM

**File:** [`src/backend/conversations/strategist_service.py:664-676`](src/backend/conversations/strategist_service.py:664)

After [`multi_hub_search()`](src/backend/conversations/global_rag_service.py:194) returns chunks, they are passed directly to [`build_global_context()`](src/backend/conversations/global_rag_service.py:270) and then into the LLM analysis prompt. There is **no filtering or relevance check** on the retrieved chunks.

If the search returns chunks about false testimony (Article 650) instead of lease/rental law, those chunks are included verbatim in the prompt. The LLM is instructed to _"Use this to ground your analysis"_, so it tries to incorporate them, leading to the irrelevant analysis.

---

### Root Cause #3: Analysis prompt doesn't handle poor context gracefully

**File:** [`src/backend/conversations/strategist_service.py:778-826`](src/backend/conversations/strategist_service.py:778)

The [`_build_analysis_prompt()`](src/backend/conversations/strategist_service.py:778) method includes the legal context with the instruction _"Use this to ground your analysis"_. When the context is irrelevant, the LLM has no instruction to fall back to general legal knowledge or to ignore irrelevant context.

Additionally, the prompt doesn't include the case description as a natural language description for the LLM to understand the case — it only passes the raw facts JSON again.

---

### Root Cause #4: Fallback report activation when `raw_report` is missing

**File:** [`src/backend/conversations/strategist_service.py:1158-1169`](src/backend/conversations/strategist_service.py:1158)

When the LLM doesn't include a `raw_report` field in its JSON output (common when the context is poor and the LLM struggles), the code calls [`_build_fallback_report()`](src/backend/conversations/strategist_service.py:1184). This generates a report from the structured fields (`summary`, `strengths`, `weaknesses`, etc.), which may be generic if the LLM had poor context.

The output structure (`خلاصه`, `نقاط قوت`, `نقاط ضعف`, `ریسک‌ها`, `توصیه‌ها`, `قوانین مرتبط`, `رویه‌های قضایی مرتبط`) matches exactly what the user observed, confirming this fallback path was triggered.

---

## Refactoring Plan

### Step 1: Rewrite `_build_case_description` to produce a fluent Persian legal description

**File:** [`src/backend/conversations/strategist_service.py:757`](src/backend/conversations/strategist_service.py:757)

**What to change:** Replace the JSON dump with a natural language Persian legal case description optimized for semantic search.

**Implementation:**
```python
def _build_case_description(self, case_type: str, facts: dict[str, Any]) -> str:
    """Build a fluent Persian legal case description for semantic search.
    
    Produces a natural language description optimized for embedding similarity
    with legal documents in the knowledge base, rather than a JSON dump.
    """
    case_type_labels = {
        "contract_dispute": "اختلافات قراردادی",
        "family_law": "دعاوی خانواده",
        "criminal": "دعاوی کیفری",
        "civil": "دعاوی حقوقی",
        "labour": "دعاوی کار و کارگری",
        "inheritance": "دعاوی ارث",
        "property": "دعاوی ملکی",
        "other": "سایر",
    }
    
    parts = [f"پرونده {case_type_labels.get(case_type, case_type)}"]
    
    # Add parties
    parties = facts.get("parties", {})
    if parties:
        if isinstance(parties, dict):
            party_str = " و ".join(
                f"{k}: {v}" for k, v in parties.items()
            )
            parts.append(f"طرفین دعوا: {party_str}")
        elif isinstance(parties, str):
            parts.append(f"طرفین دعوا: {parties}")
    
    # Add claims
    claims = facts.get("claims", "")
    if claims:
        parts.append(f"خواسته: {claims}")
    
    # Add amount
    amount = facts.get("amount")
    if amount:
        try:
            amount_str = f"{int(amount):,}" if float(amount) == int(float(amount)) else str(amount)
            parts.append(f"مبلغ: {amount_str} تومان")
        except (ValueError, TypeError):
            parts.append(f"مبلغ: {amount}")
    
    # Add timeline
    timeline = facts.get("timeline", "")
    if timeline:
        parts.append(f"زمان‌بندی: {timeline}")
    
    # Add jurisdiction
    jurisdiction = facts.get("jurisdiction", "")
    if jurisdiction:
        parts.append(f"مرجع قضایی: {jurisdiction}")
    
    # Add evidence
    evidence = facts.get("evidence", "")
    if evidence:
        parts.append(f"ادله و مدارک: {evidence}")
    
    # Add current status
    current_status = facts.get("current_status", "")
    if current_status:
        parts.append(f"وضعیت فعلی: {current_status}")
    
    # Add any other facts as key-value pairs
    for key, value in facts.items():
        if key not in ("parties", "claims", "amount", "timeline", 
                       "jurisdiction", "evidence", "current_status"):
            if isinstance(value, str) and value:
                parts.append(f"{key}: {value}")
    
    return " | ".join(parts)
```

**Example output for the rental case:**
```
پرونده اختلافات قراردادی | طرفین دعوا: موجر: کاربر و مستاجر: نامشخص | خواسته: عدم پرداخت اجاره و تخلیه | مبلغ: ۶۰,۰۰۰,۰۰۰ تومان | زمان‌بندی: قرارداد یک‌ساله از ۱۴۰۳/۰۳/۰۱ تا ۱۴۰۴/۰۳/۰۱ | مرجع قضایی: تهران | ادله و مدارک: قرارداد کتبی عادی
```

This will produce much better embedding similarity with legal documents about lease/rental law.

---

### Step 2: Add chunk relevance filtering

**File:** [`src/backend/conversations/strategist_service.py:664-676`](src/backend/conversations/strategist_service.py:664)

**What to change:** After retrieving chunks from `multi_hub_search`, filter them by relevance to the case type before passing to the LLM.

**Implementation:** Add a `_filter_relevant_chunks` method that:
1. Checks if chunks contain keywords relevant to the case type
2. Removes chunks with very low relevance scores
3. Logs filtering decisions for debugging

```python
def _filter_relevant_chunks(
    self,
    all_chunks: list[dict[str, Any]],
    case_type: str,
) -> list[dict[str, Any]]:
    """Filter chunks by relevance to the case type.
    
    Removes chunks that are clearly irrelevant to avoid confusing the LLM.
    """
    # Case-type-specific keywords for relevance filtering
    case_keywords = {
        "contract_dispute": [
            "قرارداد", "اجاره", "موجر", "مستاجر", "تخلیه", "اجاره بها",
            "فسخ", "انقضا", "مدت", "عقد", "التزام", "تعهد", "ماده",
        ],
        "family_law": [
            "طلاق", "مهریه", "نفقه", "حضانت", "ازدواج", "نکاح",
        ],
        "criminal": [
            "مجازات", "جرم", "کیفر", "حبس", "جزای نقدی", "شکایت",
        ],
        # ... other case types
    }
    
    keywords = case_keywords.get(case_type, [])
    if not keywords:
        return all_chunks
    
    filtered = []
    for chunk in all_chunks:
        content = chunk.get("content", "")
        score = chunk.get("relevance_score", 0)
        
        # Check if chunk contains any relevant keywords
        has_keyword = any(kw in content for kw in keywords)
        
        # Keep chunks with high relevance scores even without keywords
        # (they may contain semantically relevant content)
        if has_keyword or score >= 0.5:
            filtered.append(chunk)
        else:
            logger.debug(
                "_filter_relevant_chunks: Filtered out chunk "
                "(score=%.4f, no relevant keywords): %.100s",
                score, content,
            )
    
    logger.info(
        "_filter_relevant_chunks: Filtered %d/%d chunks for case_type=%s",
        len(all_chunks) - len(filtered),
        len(all_chunks),
        case_type,
    )
    
    return filtered
```

---

### Step 3: Update the analysis prompt to handle poor context gracefully

**File:** [`src/backend/conversations/strategist_service.py:778-826`](src/backend/conversations/strategist_service.py:778)

**What to change:** 
1. Include the natural language case description (from Step 1) in the prompt
2. Add instructions for handling irrelevant or missing context
3. Instruct the LLM to rely on general legal knowledge when context is poor

**Key prompt additions:**
- _"If the retrieved legal context is not relevant to the case, ignore it and base your analysis on general legal principles."_
- Include the case description as a separate section for the LLM to understand the case
- Add: _"Do NOT cite laws or precedents that are not relevant to the case facts."_

---

### Step 4: Add diagnostic logging at each pipeline stage

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py)

**What to change:** Add structured logging at key decision points to make debugging easier:

1. Log the case description produced by `_build_case_description`
2. Log the router result (active hubs, queries)
3. Log the number of chunks per hub and their relevance scores
4. Log how many chunks were filtered out (after Step 2)
5. Log whether `raw_report` was present or fallback was used
6. Log the parsing strategy that succeeded

---

### Step 5: Create a diagnostic test script for the rental case

**File:** `scripts/diag_step_rental_case.py` (new)

**What to do:** Create a diagnostic script similar to [`scripts/diag_step4_trace_search.py`](scripts/diag_step4_trace_search.py) but specifically for the rental/lease case, to verify the fix works.

The script should:
1. Build a case description using the new `_build_case_description`
2. Call `route_question()` and log the router result
3. Call `multi_hub_search()` and log the chunks per hub
4. Check if any chunks about lease/rental law (قانون روابط موجر و مستأجر) were found
5. Test with manual Persian legal queries about rental law

---

## Execution Order

| Step | Description | Files Changed | Risk |
|------|-------------|---------------|------|
| 1 | Rewrite `_build_case_description` | `strategist_service.py` | Low — isolated change, easy to test |
| 2 | Add chunk relevance filtering | `strategist_service.py` | Low — only removes chunks, doesn't change pipeline |
| 3 | Update analysis prompt | `strategist_service.py` | Medium — changes LLM behavior |
| 4 | Add diagnostic logging | `strategist_service.py` | Low — logging only |
| 5 | Create diagnostic test script | `scripts/diag_step_rental_case.py` (new) | Low — new file |

## Verification

After implementing the fix, verify by:

1. **Running the diagnostic script** to confirm relevant chunks are retrieved for the rental case
2. **Running the existing tests** to ensure no regressions:
   ```
   docker-compose exec backend pytest conversations/tests/
   ```
3. **Manual test** via the Strategist UI with a rental case description
4. **Check logs** for the new diagnostic messages to confirm the pipeline is working correctly
