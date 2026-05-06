# Fix Plan: "Network Error" for Persian Queries with Arabic/Persian Character Variants

## Problem Summary

When the user asks a Persian question containing certain characters (specifically queries with Arabic/Persian character variants like `ي` vs `ی` or `ك` vs `ک`), the frontend shows **"Network Error"** instead of getting a response. Simpler queries like `"hi"` or `"سند در مورد چیه"` work fine.

The specific failing query is: **"عقد جایز و لازم چه تفاوتی دارند؟"**

## Root Cause

The `formulate_query()` function in [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py:132) sends the user's raw query to the **chat provider (LLM)** to generate optimized `fts_query` and `vector_query` strings. This happens **only** when `len(user_query) >= 10` characters (line 160).

**The problem:** The user query may contain Arabic character variants (Yeh `ي` U+064A, Kaf `ك` U+0643) that are visually identical to their Persian counterparts (Yeh `ی` U+06CC, Kaf `ک` U+06A9) but have different Unicode codepoints. When these mixed characters are sent to the LLM, it can produce malformed output or the API call can fail.

The [`PersianNormalizer`](src/backend/documents/services/persian_normalizer.py:77) already has the `_ARABIC_TO_PERSIAN` translation table (`{0x064A: 0x06CC, 0x0643: 0x06A9}`) and the `normalize_for_fts()` method, but **this normalization is NOT applied to user queries** before they're sent to the LLM for formulation.

## Fix 1: Normalize Arabic→Persian Chars in `formulate_query()`

**File:** [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py:132)

**What to do:** Add Arabic→Persian character normalization to the `user_query` **before** it's sent to the LLM in `formulate_query()`.

**Exact code change:**

At the top of the file, add the import:

```python
from documents.services.persian_normalizer import PersianNormalizer
```

Inside `formulate_query()`, right after the function signature and docstring (before the `if len(user_query) < 10` check), add:

```python
# Normalize Arabic character variants to Persian equivalents
# This prevents LLM failures caused by mixed Unicode codepoints
# (e.g., Arabic Yeh U+064A → Persian Yeh U+06CC)
_ARABIC_TO_PERSIAN = str.maketrans({
    '\u064A': '\u06CC',  # Arabic Yeh → Persian Yeh
    '\u0643': '\u06A9',  # Arabic Kaf → Persian Kaf
})
user_query = user_query.translate(_ARABIC_TO_PERSIAN)
```

**Why this works:** By normalizing before the LLM call, we ensure consistent Persian characters throughout the pipeline. The LLM receives clean Persian text and produces reliable JSON output.

## Fix 2: Normalize Arabic→Persian Chars in Serializer Validation

**File:** [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py:192)

**What to do:** Add a `validate_content()` method to `AskQuestionSerializer` that normalizes Arabic→Persian characters at the input layer.

**Exact code change:**

Add to the `AskQuestionSerializer` class:

```python
def validate_content(self, value: str) -> str:
    """Normalize Arabic character variants to Persian equivalents."""
    _ARABIC_TO_PERSIAN = str.maketrans({
        '\u064A': '\u06CC',  # Arabic Yeh → Persian Yeh
        '\u0643': '\u06A9',  # Arabic Kaf → Persian Kaf
    })
    return value.translate(_ARABIC_TO_PERSIAN)
```

**Why this works:** This normalizes characters at the earliest possible point — the input validation layer. Every query that enters the system gets normalized, providing defense-in-depth alongside Fix 1.

## Testing Instructions

1. **Unit test:** Verify that `formulate_query()` normalizes Arabic Yeh/Kaf to Persian equivalents before the LLM call
2. **Integration test:** Send the failing query `"عقد جایز و لازم چه تفاوتی دارند؟"` through the full RAG pipeline and verify it succeeds
3. **Manual test:** Test the failing query in the browser after fixes
4. **Regression test:** Verify that previously working queries (`"hi"`, `"سند در مورد چیه"`) still work

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py) | Add Arabic→Persian character normalization before LLM call |
| 2 | [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | Add character normalization in `AskQuestionSerializer.validate_content()` |
| 3 | [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update WIP context |
