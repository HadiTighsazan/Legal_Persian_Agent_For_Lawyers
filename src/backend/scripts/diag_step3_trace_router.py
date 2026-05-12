"""
Diagnostic Step 3: Trace the Question Router for the specific query.

This script:
1. Calls route_question() with the exact user query about military service
2. Logs the full RouterResult including which hubs were activated and the queries
3. Also tests with a simplified version of the query
"""
import os
import sys
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from conversations.question_router import route_question, RouterResult

print("=" * 70)
print("STEP 3: TRACE QUESTION ROUTER FOR MILITARY SERVICE QUERY")
print("=" * 70)

# The exact user query
USER_QUERY = "پسری که مشمول باشه ولی خودشو معرفی نکنه جرمش فرار از خدمت است؟"

print(f"\n[INPUT] User query: {USER_QUERY}")
print(f"[INPUT] Query length: {len(USER_QUERY)} chars")

# ---------------------------------------------------------------------------
# 3a. Call the question router
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("3a: CALLING route_question()")
print("-" * 70)

try:
    result: RouterResult = route_question(USER_QUERY)
    
    print(f"\n[RESULT] Router reasoning: {result.reasoning}")
    print(f"\n[RESULT] Sub-queries per hub:")
    
    for hub_type, sub_query in result.sub_queries.items():
        print(f"\n  ┌─ Hub: {hub_type}")
        print(f"  │  Active: {'YES' if (sub_query.fts_query or sub_query.vector_query) else 'NO'}")
        print(f"  │  FTS Query ({len(sub_query.fts_query)} chars):")
        print(f"  │    {sub_query.fts_query}")
        print(f"  │  Vector Query ({len(sub_query.vector_query)} chars):")
        print(f"  │    {sub_query.vector_query}")
        
        # Check if queries contain military-related terms
        military_terms = ["سرباز", "مشمول", "فرار", "خدمت", "نظامی", "نیروهای مسلح"]
        fts_has_military = any(term in sub_query.fts_query for term in military_terms)
        vec_has_military = any(term in sub_query.vector_query for term in military_terms)
        print(f"  │  FTS contains military terms: {'✓' if fts_has_military else '✗'}")
        print(f"  │  Vector contains military terms: {'✓' if vec_has_military else '✗'}")
    
    active_hubs = [
        hub for hub, sq in result.sub_queries.items()
        if sq.fts_query or sq.vector_query
    ]
    print(f"\n[SUMMARY] Active hubs: {active_hubs}")
    
except Exception as e:
    print(f"\n[ERROR] route_question() failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ---------------------------------------------------------------------------
# 3b. Test with a simplified keyword-style query
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("3b: TESTING WITH SIMPLIFIED KEYWORD QUERY")
print("-" * 70)

simplified_query = "فرار از خدمت مشمول غایب"
print(f"\n[INPUT] Simplified query: {simplified_query}")

try:
    result2: RouterResult = route_question(simplified_query)
    
    print(f"\n[RESULT] Router reasoning: {result2.reasoning}")
    print(f"\n[RESULT] Sub-queries per hub:")
    
    for hub_type, sub_query in result2.sub_queries.items():
        print(f"\n  ┌─ Hub: {hub_type}")
        print(f"  │  Active: {'YES' if (sub_query.fts_query or sub_query.vector_query) else 'NO'}")
        print(f"  │  FTS Query: {sub_query.fts_query}")
        print(f"  │  Vector Query: {sub_query.vector_query}")
    
    active_hubs2 = [
        hub for hub, sq in result2.sub_queries.items()
        if sq.fts_query or sq.vector_query
    ]
    print(f"\n[SUMMARY] Active hubs: {active_hubs2}")
    
except Exception as e:
    print(f"\n[ERROR] route_question() failed: {type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
# 3c. Test with a very specific legal query
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("3c: TESTING WITH SPECIFIC LEGAL QUERY")
print("-" * 70)

legal_query = "طبق قانون مجازات جرایم نیروهای مسلح، مجازات فرار از خدمت چیست؟"
print(f"\n[INPUT] Legal query: {legal_query}")

try:
    result3: RouterResult = route_question(legal_query)
    
    print(f"\n[RESULT] Router reasoning: {result3.reasoning}")
    print(f"\n[RESULT] Sub-queries per hub:")
    
    for hub_type, sub_query in result3.sub_queries.items():
        print(f"\n  ┌─ Hub: {hub_type}")
        print(f"  │  Active: {'YES' if (sub_query.fts_query or sub_query.vector_query) else 'NO'}")
        print(f"  │  FTS Query: {sub_query.fts_query}")
        print(f"  │  Vector Query: {sub_query.vector_query}")
    
    active_hubs3 = [
        hub for hub, sq in result3.sub_queries.items()
        if sq.fts_query or sq.vector_query
    ]
    print(f"\n[SUMMARY] Active hubs: {active_hubs3}")
    
except Exception as e:
    print(f"\n[ERROR] route_question() failed: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("STEP 3 COMPLETE")
print("=" * 70)
