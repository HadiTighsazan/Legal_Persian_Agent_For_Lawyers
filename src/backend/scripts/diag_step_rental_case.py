"""
Diagnostic Step: Rental Case — Trace the Full Strategist Pipeline.

This script tests the pipeline specifically for a rental dispute case
(موجر و مستاجر) to verify the RAG retrieval fix works correctly.

It:
1. Builds a case description using the updated ``_build_case_description``.
2. Calls ``route_question()`` and prints the router results.
3. Calls ``multi_hub_search()`` and prints chunks per hub.
4. Verifies if chunks related to "قانون روابط موجر و مستأجر" were retrieved.

Usage:
    docker-compose exec backend python scripts/diag_step_rental_case.py
"""
import os
import sys

# Ensure the project root (/app) is on sys.path so Django can find 'config'
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from conversations.strategist_service import StrategicAnalyzer
from conversations.question_router import route_question
from conversations.global_rag_service import multi_hub_search

# ---------------------------------------------------------------------------
# Rental dispute case facts (موجر و مستاجر)
# ---------------------------------------------------------------------------
RENTAL_CASE_TYPE = "contract_dispute"
RENTAL_FACTS: dict[str, object] = {
    "parties": {
        "موجر": "کاربر",
        "مستاجر": "نامشخص",
    },
    "claims": "عدم پرداخت اجاره و تخلیه",
    "amount": 60000000,
    "timeline": "قرارداد یک‌ساله از ۱۴۰۳/۰۳/۰۱ تا ۱۴۰۴/۰۳/۰۱",
    "jurisdiction": "تهران",
    "evidence": "قرارداد کتبی عادی",
    "current_status": "مستاجر از پرداخت اجاره خودداری کرده و ملک را تخلیه ننموده",
}

# Keywords to check in retrieved chunks
RENTAL_KEYWORDS = [
    "موجر", "مستاجر", "اجاره", "تخلیه", "قانون روابط موجر و مستأجر",
    "رابطه استیجاری", "اجاره بها", "سرقفلی", "حق کسب و پیشه",
]

print("=" * 70)
print("DIAGNOSTIC: RENTAL CASE (موجر و مستاجر) — FULL PIPELINE TRACE")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Build case description using the updated method
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("1: BUILD CASE DESCRIPTION (updated _build_case_description)")
print("-" * 70)

try:
    analyzer = StrategicAnalyzer()
    case_description = analyzer._build_case_description(
        RENTAL_CASE_TYPE, RENTAL_FACTS,
    )
    print("[OK] Case description generated successfully")
    print(f"\n{case_description}\n")
except Exception as e:
    print(f"[ERROR] _build_case_description() failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Route the case to relevant legal hubs
# ---------------------------------------------------------------------------
print("-" * 70)
print("2: ROUTE QUESTION (route_question)")
print("-" * 70)

try:
    router_result = route_question(case_description)
    print(f"[OK] Router result obtained")
    print(f"[INFO] Reasoning: {router_result.reasoning}")

    active_hubs = []
    for hub_type, sub_query in router_result.sub_queries.items():
        is_active = bool(sub_query.fts_query or sub_query.vector_query)
        status = "YES" if is_active else "NO"
        print(f"  Hub '{hub_type}': active={status}")
        if is_active:
            active_hubs.append(hub_type)
            print(f"    fts_query:    {sub_query.fts_query}")
            print(f"    vector_query: {sub_query.vector_query}")

    if not active_hubs:
        print("[WARN] No active hubs identified — pipeline may fall back to all hubs")
except Exception as e:
    print(f"[ERROR] route_question() failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Run multi_hub_search
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("3: MULTI-HUB SEARCH (multi_hub_search)")
print("-" * 70)

try:
    hub_results = multi_hub_search(
        router_result=router_result,
        top_k_per_hub=5,
    )

    total_chunks = 0
    for hub_type, hub_data in hub_results.items():
        chunks = hub_data.get("chunks", [])
        sub_query = hub_data.get("sub_query")
        error = hub_data.get("error")
        total_chunks += len(chunks)

        print(f"\n  ┌─ Hub: {hub_type}")
        print(f"  │  Chunks retrieved: {len(chunks)}")
        if error:
            print(f"  │  ERROR: {error}")

        if chunks:
            print(f"  │  Chunks:")
            for i, chunk in enumerate(chunks):
                content = chunk.get("content", "")
                score = chunk.get("relevance_score", 0.0)
                chunk_idx = chunk.get("chunk_index", "?")
                # Truncate content for display
                preview = content[:200].replace("\n", " ")
                print(f"  │  [{i+1}] idx={chunk_idx} score={score:.4f}")
                print(f"  │      {preview}...")

                # Check for rental-related terms
                matched_terms = [
                    kw for kw in RENTAL_KEYWORDS if kw in content
                ]
                if matched_terms:
                    print(
                        f"  │  ⭐ RENTAL-RELATED! "
                        f"Matched terms: {', '.join(matched_terms)}"
                    )
        else:
            print(f"  │  (no chunks retrieved)")

    print(f"\n  TOTAL chunks across all hubs: {total_chunks}")
except Exception as e:
    print(f"[ERROR] multi_hub_search() failed: {e}")
    import traceback
    traceback.print_exc()

# ---------------------------------------------------------------------------
# 4. Verify retrieval of rental-law-related chunks
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("4: VERIFY RENTAL LAW RETRIEVAL (قانون روابط موجر و مستأجر)")
print("-" * 70)

rental_chunks_found = 0
for hub_type, hub_data in hub_results.items():
    for chunk in hub_data.get("chunks", []):
        content = chunk.get("content", "")
        if any(kw in content for kw in RENTAL_KEYWORDS):
            rental_chunks_found += 1

if rental_chunks_found > 0:
    print(
        f"[OK] Found {rental_chunks_found} rental-related chunk(s) "
        f"across all hubs"
    )
else:
    print("[WARN] No rental-related chunks found in search results")
    print("       This may indicate a retrieval gap for rental law content.")

# ---------------------------------------------------------------------------
# 5. Manual Persian legal queries about rental law
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("5: MANUAL PERSIAN LEGAL QUERIES ABOUT RENTAL LAW")
print("-" * 70)

manual_queries = [
    "قانون روابط موجر و مستأجر",
    "اجاره نامه و تخلیه",
    "حقوق موجر و مستاجر",
    "فسخ قرارداد اجاره",
    "دعاوی تخلیه و اجاره بها",
]

for query in manual_queries:
    print(f"\n  Query: {query}")
    try:
        manual_router = route_question(query)
        manual_results = multi_hub_search(
            router_result=manual_router,
            top_k_per_hub=3,
        )
        total = sum(
            len(d.get("chunks", []))
            for d in manual_results.values()
        )
        print(f"  Total chunks retrieved: {total}")

        # Check for rental keywords in results
        rental_in_results = 0
        for d in manual_results.values():
            for c in d.get("chunks", []):
                if any(kw in c.get("content", "") for kw in RENTAL_KEYWORDS):
                    rental_in_results += 1
        if rental_in_results > 0:
            print(f"  ⭐ {rental_in_results} rental-related chunk(s) found")
        else:
            print(f"  (no rental-related chunks)")
    except Exception as e:
        print(f"  [ERROR] {e}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
