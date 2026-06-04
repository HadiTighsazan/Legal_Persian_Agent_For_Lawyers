# Strategist Parsing Error — Root Cause Analysis & Fix Plan

## Problem

When using the "Strategist" mode, after the interview phase completes and the system attempts to generate a strategic analysis report, the user sees:

> **خطا در پردازش**
> متأسفانه در پردازش پاسخ تحلیل استراتژیک خطایی رخ داد. لطفاً دوباره تلاش کنید.
> **جزئیات فنی**: سیستم قادر به تجزیه پاسخ دریافتی از مدل زبانی نبود.

This error originates from [`_build_error_result()`](src/backend/conversations/strategist_service.py:909) which is called when [`parse_analysis_response()`](src/backend/conversations/strategist_service.py:938) fails to parse the LLM's JSON response.

## Flow Trace

```
StrategistPage (React)
  → ChatWindow (mode="strategist")
    → conversationStore.sendMessageStream()
      → api.sendMessageStream() → POST /api/conversations/{id}/messages/stream/
        → ConversationMessageStreamView (views.py:490)
          → strategist_service.process_message() (strategist_service.py:1259)
            → FactExtractor.extract() ← works fine (interview questions)
            → CompletenessChecker.check() ← works fine
            → StrategicAnalyzer.analyze() (strategist_service.py:600)
              → LLM call with max_tokens=2000
              → parse_analysis_response() ← FAILS HERE
                → _extract_json_from_fence() ← returns None
                → _build_error_result() ← returns error report
```

## Root Cause Analysis

### Root Cause #1: Insufficient Token Limit (PRIMARY)

[`_ANALYSIS_MAX_TOKENS = 2000`](src/backend/conversations/strategist_service.py:67) is too low for the strategic analysis LLM call.

The [`STRATEGIC_ANALYSIS_SYSTEM_PROMPT`](src/backend/conversations/strategist_service.py:223) instructs the LLM to generate a JSON response containing a **full Persian markdown report** with 8 sections (خلاصه, نقاط قوت, نقاط ضعف, ریسک‌ها, توصیه‌ها, قوانین مرتبط, رویه‌های قضایی مرتبط) plus structured fields.

A comprehensive Persian legal analysis report easily exceeds 2000 tokens. When the LLM hits the token limit, the response is **truncated mid-JSON**, producing invalid JSON that cannot be parsed.

### Root Cause #2: Regex Fragility in `_extract_json_from_fence`

The regex at [`_extract_json_from_fence()`](src/backend/conversations/strategist_service.py:859):

```python
fence_pattern = r'```(?:json)?\s*\n(.*?)```'
```

This regex **requires** a closing ` ``` ` fence. When the LLM response is truncated (due to Root Cause #1), the closing fence is missing, so the regex returns `None`.

The fallback (Pattern 2) checks if the stripped content starts with `{` or `[`, but the raw content starts with ` ```json`, not `{`. So the fallback also fails.

### Root Cause #3: Weak Regex Fallback `_extract_fields_via_regex`

The regex fallback at [`_extract_fields_via_regex()`](src/backend/conversations/strategist_service.py:890) only extracts two fields:

```python
prob = re.search(r'"success_probability"\s*:\s*([0-9.]+)', text)
summary = re.search(r'"summary"\s*:\s*"([^"]+)"', text)
```

The `summary` regex `"([^"]+)"` cannot handle Persian text containing `"` characters or newlines. If the summary contains Persian quotes or line breaks, this regex fails, returning `None`, which triggers the error result.

### Why Fact Extraction Works But Analysis Fails

The [`FactExtractor._parse_extraction_response()`](src/backend/conversations/strategist_service.py:372) uses a **different, more robust** parsing approach:
1. Manually strips ``` fences by finding newlines and checking endings
2. Tries `json.loads` then `json.loads(strict=False)`
3. Returns a default `FactExtractionResult()` on failure (graceful degradation)

The [`parse_analysis_response()`](src/backend/conversations/strategist_service.py:938) uses a **more fragile** approach:
1. Uses regex to extract JSON from fences (fails if truncated)
2. Multiple JSON parsing attempts
3. Regex fallback (only 2 fields)
4. Returns error result on failure (no graceful degradation)

## Fix Plan

### Fix 1: Increase `_ANALYSIS_MAX_TOKENS`

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py:67)

Change `_ANALYSIS_MAX_TOKENS` from `2000` to `8192`.

**Confirmed by logs:** The LLM response requires **9075 total tokens**. With `max_tokens=2000`, the output is truncated mid-JSON. Setting to `8192` provides sufficient headroom for the full Persian legal analysis report.

Also increase `_REPORT_MAX_TOKENS` from `3000` to `8192` for consistency.

### Fix 2: Improve `_extract_json_from_fence` for Truncated Responses

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py:849)

Modify the regex to handle cases where the closing ``` is missing (truncated response):

```python
# Current (fragile):
fence_pattern = r'```(?:json)?\s*\n(.*?)```'

# Fixed (handles missing closing fence):
fence_pattern = r'```(?:json)?\s*\n(.*?)(?:```|$)'
```

Also add a third fallback: if the content starts with ` ```json` or ` ``` `, strip the fence prefix and try to parse the rest as JSON even without a closing fence.

### Fix 3: Improve `_extract_fields_via_regex` for Persian Text

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py:890)

Enhance the regex fallback to handle more fields and Persian text with newlines:

- Use `re.DOTALL` flag for multi-line field values
- Add extraction for `strengths`, `weaknesses`, `risks`, `recommendations` arrays
- Handle Persian quotation marks (`«»`, `"`)
- Handle `raw_report` field extraction

### Fix 4: Graceful Degradation in `parse_analysis_response`

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py:938)

Instead of immediately returning `_build_error_result()` when `_extract_json_from_fence` returns `None`, add additional fallback strategies:

1. Try to find any `{...}` block in the raw content using a more lenient regex
2. Try to extract individual fields using broader regex patterns directly on the raw content
3. Only return error result as absolute last resort

### Fix 5: Fix `_save_strategic_report` UniqueViolation on Retry

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py:1500)

The [`StrategicReport`](src/backend/conversations/models.py:105) model has a `OneToOneField` to `Conversation` (line 113). Using `StrategicReport.objects.create()` will raise an `IntegrityError`/`UniqueViolation` if a report already exists for that conversation (e.g., if the user retries after a failure).

Change to `StrategicReport.objects.update_or_create()` with `conversation_id` as the lookup field, so retries overwrite the previous report instead of crashing.

### Fix 6: Update Tests

**File:** [`src/backend/conversations/tests/test_strategist_parsing.py`](src/backend/conversations/tests/test_strategist_parsing.py)

Add test cases for:
- Truncated JSON response (missing closing fence)
- Persian text with newlines in summary/raw_report
- Very long Persian markdown report
- JSON with unescaped newlines in string values
- `_save_strategic_report` idempotency (update_or_create on retry)

## Verification

After fixes, the following scenario should work:
1. User describes a legal case in Strategist mode
2. System asks clarifying questions (interview phase)
3. User provides all details
4. System generates strategic analysis report successfully
5. Report is displayed in Persian with all sections

## Files to Modify

| File | Changes |
|------|---------|
| `src/backend/conversations/strategist_service.py` | Lines 67, 849-869, 890-906, 938-964 |
| `src/backend/conversations/tests/test_strategist_parsing.py` | Add new test cases |
| `docs/active-task/wip-context.md` | Update with changes |
