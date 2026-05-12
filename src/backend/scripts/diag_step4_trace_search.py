"""
Diagnostic Step 4: Trace the Multi-Hub Search for the specific query.

This script:
1. Takes the RouterResult from Step 3 (or generates it fresh)
2. For each active hub, calls multi_hub_search()
3. Logs the number of results from each search method
4. Shows the top chunks from each hub
5. Checks if any military-service-related chunks were found
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from conversations.question_router import route_question
from conversations.global_rag_service import multi_hub_search
from documents.services.embedding_service import embed_query
from documents.services.search_service import (
    cross_document_hybrid_search,
    _vector_search_by_hub,
    _keyword_search_by_hub,
    _trigram_search_by_hub,
)
from documents.models import DocumentChunk

print("=" * 70)
print("STEP 4: TRACE MULTI-HUB SEARCH FOR MILITARY SERVICE QUERY")
print("=" * 70)

USER_QUERY = "پسری که مشمول باشه ولی خودشو معرفی نکنه جرمش فرار از خدمت است؟"

# ---------------------------------------------------------------------------
# 4a. Get the router result
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("4a: GETTING ROUTER RESULT")
print("-" * 70)

try:
    router_result = route_question(USER_QUERY)
    print(f"[OK] Router result obtained")
    print(f"[INFO] Reasoning: {router_result.reasoning}")
    
    for hub_type, sub_query in router_result.sub_queries.items():
        active = "YES" if (sub_query.fts_query or sub_query.vector_query) else "NO"
        print(f"  Hub '{hub_type}': active={active}")
        if active == "YES":
            print(f"    fts_query:    {sub_query.fts_query[:100]}...")
            print(f"    vector_query: {sub_query.vector_query[:100]}...")
except Exception as e:
    print(f"[ERROR] route_question() failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ---------------------------------------------------------------------------
# 4b. Run multi_hub_search
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("4b: RUNNING multi_hub_search()")
print("-" * 70)

try:
    hub_results = multi_hub_search(
        router_result=router_result,
        top_k_per_hub=5,
    )
    
    for hub_type, hub_data in hub_results.items():
        chunks = hub_data.get("chunks", [])
        sub_query = hub_data.get("sub_query")
        error = hub_data.get("error")
        
        print(f"\n  ┌─ Hub: {hub_type}")
        print(f"  │  Chunks retrieved: {len(chunks)}")
        if error:
            print(f"  │  ERROR: {error}")
        
        if chunks:
            print(f"  │  Top chunks:")
            for i, chunk in enumerate(chunks[:5]):
                content = chunk.get("content", "")[:150]
                score = chunk.get("relevance_score", 0)
                chunk_idx = chunk.get("chunk_index", "?")
                doc_title = "?"
                # Try to get document title
                try:
                    c_obj = DocumentChunk.objects.filter(
                        chunk_index=chunk_idx,
                        content__startswith=content[:50]
                    ).first()
                    if c_obj:
                        doc_title = c_obj.document.title
                except:
                    pass
                print(f"  │  [{i+1}] idx={chunk_idx} score={score:.4f} doc={doc_title}")
                print(f"  │      {content}")
                
                # Check if this chunk is about military service
                military_terms = ["سرباز", "مشمول", "فرار", "خدمت", "نظامی", "نیروهای مسلح"]
                has_military = any(term in content for term in military_terms)
                if has_military:
                    print(f"  │  ⭐ CONTAINS MILITARY TERMS!")
        else:
            print(f"  │  (no chunks retrieved)")
            
except Exception as e:
    print(f"[ERROR] multi_hub_search() failed: {e}")
    import traceback
    traceback.print_exc()

# ---------------------------------------------------------------------------
# 4c. Per-search-method breakdown for each hub
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("4c: PER-SEARCH-METHOD BREAKDOWN")
print("-" * 70)

for hub_type, sub_query in router_result.sub_queries.items():
    if not sub_query.fts_query and not sub_query.vector_query:
        continue
    
    print(f"\n  Hub: {hub_type}")
    
    # Vector search
    try:
        query_embedding = embed_query(sub_query.vector_query)
        vec_results = _vector_search_by_hub(
            hub_type=hub_type,
            query_vector=query_embedding,
            top_k=60,  # RRF depth
        )
        print(f"  │  Vector search: {len(vec_results)} results")
        if vec_results:
            scores = [f"{r['relevance_score']:.4f}" for r in vec_results[:3]]
            print(f"  │    Top 3 vector scores: {scores}")
            # Check for military content
            for r in vec_results[:10]:
                if any(term in r["content"] for term in ["سرباز", "مشمول", "فرار", "خدمت", "نظامی", "نیروهای مسلح"]):
                    print(f"  │    ⭐ Military chunk at rank {vec_results.index(r)+1}: idx={r['chunk_index']}")
                    break
    except Exception as e:
        print(f"  │  Vector search FAILED: {e}")
    
    # Keyword search (FTS)
    try:
        kw_results = _keyword_search_by_hub(
            hub_type=hub_type,
            query_text=sub_query.fts_query,
            top_k=60,
        )
        print(f"  │  Keyword search: {len(kw_results)} results")
        if kw_results:
            scores = [f"{r['relevance_score']:.4f}" for r in kw_results[:3]]
            print(f"  │    Top 3 keyword scores: {scores}")
            for r in kw_results[:10]:
                if any(term in r["content"] for term in ["سرباز", "مشمول", "فرار", "خدمت", "نظامی", "نیروهای مسلح"]):
                    print(f"  │    ⭐ Military chunk at rank {kw_results.index(r)+1}: idx={r['chunk_index']}")
                    break
        else:
            print(f"  │    ⚠ FTS returned ZERO results!")
    except Exception as e:
        print(f"  │  Keyword search FAILED: {e}")
    
    # Trigram search
    try:
        tri_results = _trigram_search_by_hub(
            hub_type=hub_type,
            query_text=sub_query.fts_query,
            top_k=60,
        )
        print(f"  │  Trigram search: {len(tri_results)} results")
        if tri_results:
            scores = [f"{r['relevance_score']:.4f}" for r in tri_results[:3]]
            print(f"  │    Top 3 trigram scores: {scores}")
    except Exception as e:
        print(f"  │  Trigram search FAILED: {e}")

# ---------------------------------------------------------------------------
# 4d. Direct search with manual queries
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("4d: DIRECT SEARCH WITH MANUAL QUERIES")
print("-" * 70)

manual_queries = [
    "فرار از خدمت",
    "مشمول غایب",
    "قانون مجازات جرایم نیروهای مسلح",
    "تخلف از خدمت سربازی",
    "غیبت سربازی",
    "مجازات فرار از خدمت",
]

for query in manual_queries:
    print(f"\n  Query: '{query}'")
    
    for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
        try:
            # Embed the query
            query_emb = embed_query(query)
            
            # Vector search
            vec = _vector_search_by_hub(
                hub_type=hub_type,
                query_vector=query_emb,
                top_k=5,
            )
            
            # Keyword search
            kw = _keyword_search_by_hub(
                hub_type=hub_type,
                query_text=query,
                top_k=5,
            )
            
            # Trigram search
            tri = _trigram_search_by_hub(
                hub_type=hub_type,
                query_text=query,
                top_k=5,
            )
            
            # Full hybrid
            hybrid = cross_document_hybrid_search(
                hub_type=hub_type,
                query_vector=query_emb,
                query_text=query,
                top_k=5,
            )
            
            print(f"    {hub_type}: vec={len(vec)} kw={len(kw)} tri={len(tri)} hybrid={len(hybrid)}")
            
            if hybrid:
                for h in hybrid:
                    content = h["content"][:100]
                    if any(term in content for term in ["سرباز", "مشمول", "فرار", "خدمت", "نظامی", "نیروهای مسلح"]):
                        print(f"      ⭐ idx={h['chunk_index']} score={h['relevance_score']:.4f}")
                        print(f"        {content}")
        except Exception as e:
            print(f"    {hub_type}: ERROR - {e}")

print("\n" + "=" * 70)
print("STEP 4 COMPLETE")
print("=" * 70)
