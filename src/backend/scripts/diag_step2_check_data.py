"""
Diagnostic Step 2: Check what reference law data exists in the database.

This script checks:
1. All reference_law documents and their hub types
2. Chunk counts and embedding status per document
3. Specifically searches for military-service-related documents
4. Shows hub_type distribution of chunks
5. Checks a sample of chunks from each hub to see their content
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from documents.models import Document, DocumentChunk

print("=" * 70)
print("STEP 2: CHECK REFERENCE LAW DATA IN DATABASE")
print("=" * 70)

# ---------------------------------------------------------------------------
# 2a. List all reference_law documents
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("2a: ALL REFERENCE LAW DOCUMENTS")
print("-" * 70)

ref_docs = Document.objects.filter(document_type="reference_law").values(
    "id", "title", "status", "hub_type", "total_chunks"
).order_by("hub_type", "title")

if not ref_docs:
    print("\n  ⚠ NO reference_law documents found in the database!")
    print("  This means the military service laws were never imported.")
else:
    for d in ref_docs:
        chunk_count = DocumentChunk.objects.filter(document_id=d["id"]).count()
        embedded_count = DocumentChunk.objects.filter(
            document_id=d["id"], embedding__isnull=False
        ).count()
        fts_count = DocumentChunk.objects.filter(
            document_id=d["id"], search_vector__isnull=False
        ).count()
        print(f"\n  Document: {d['title']}")
        print(f"    ID:       {d['id']}")
        print(f"    Status:   {d['status']}")
        print(f"    Hub Type: {d['hub_type']}")
        print(f"    Chunks:   {chunk_count} total, {embedded_count} embedded, {fts_count} with FTS")
        if d["total_chunks"] and chunk_count != d["total_chunks"]:
            print(f"    ⚠ Mismatch: declared={d['total_chunks']} actual={chunk_count}")

# ---------------------------------------------------------------------------
# 2b. Search for military-service-related documents
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("2b: SEARCHING FOR MILITARY-SERVICE-RELATED DOCUMENTS")
print("-" * 70)

military_keywords = [
    "نیروهای مسلح",
    "خدمت",
    "سرباز",
    "مشمول",
    "فرار",
    "ارتش",
    "سپاه",
    "نظامی",
    "وظیفه",
    "اعزام",
    "غیبت",
    "پایان خدمت",
    "معافیت",
    "کارت پایان خدمت",
]

all_docs = Document.objects.filter(document_type="reference_law")
found_military = False
for keyword in military_keywords:
    matching = all_docs.filter(title__icontains=keyword)
    for d in matching:
        found_military = True
        chunk_count = DocumentChunk.objects.filter(document_id=d.id).count()
        print(f"\n  ✓ Found: '{d.title}' (hub={d.hub_type}, chunks={chunk_count})")
        # Show a sample chunk
        sample = DocumentChunk.objects.filter(document_id=d.id).first()
        if sample:
            print(f"    Sample chunk content: {sample.content[:200]}")

if not found_military:
    print("\n  ⚠ NO military-service-related documents found!")
    print("  This is a CRITICAL finding — the data may not have been imported.")

# Also search in chunk content
print("\n  Also searching in chunk content for 'سرباز' and 'نیروهای مسلح'...")
for term in ["سرباز", "نیروهای مسلح", "فرار از خدمت", "مشمول"]:
    chunks = DocumentChunk.objects.filter(
        document__document_type="reference_law",
        content__icontains=term,
    )[:3]
    if chunks:
        print(f"    '{term}' found in {len(chunks)} chunks (showing up to 3):")
        for c in chunks:
            print(f"      doc={c.document.title} hub={c.hub_type} idx={c.chunk_index}")
            print(f"      preview: {c.content[:150]}")
    else:
        print(f"    '{term}' NOT found in any reference_law chunk")

# ---------------------------------------------------------------------------
# 2c. Hub type distribution (using raw SQL for accurate counts)
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("2c: HUB TYPE DISTRIBUTION")
print("-" * 70)

from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT
            hub_type,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded,
            COUNT(*) FILTER (WHERE search_vector IS NOT NULL) as has_fts
        FROM document_chunks
        WHERE hub_type IS NOT NULL AND hub_type != ''
        GROUP BY hub_type
        ORDER BY hub_type
    """)
    rows = cursor.fetchall()

if rows:
    for row in rows:
        hub_type, total, embedded, has_fts = row
        print(f"\n  Hub: {hub_type}")
        print(f"    Total chunks:    {total}")
        print(f"    With embedding:  {embedded}")
        print(f"    With FTS vector: {has_fts}")
        if embedded < total:
            print(f"    ⚠ {total - embedded} chunks MISSING embeddings!")
else:
    print("\n  No hub_type data found in document_chunks table")

# Also check if there are chunks with NULL/empty hub_type
null_hub = DocumentChunk.objects.filter(
    document__document_type="reference_law",
    hub_type__isnull=True
) | DocumentChunk.objects.filter(
    document__document_type="reference_law",
    hub_type=""
)
null_count = null_hub.count()
if null_count > 0:
    print(f"\n  ⚠ {null_count} reference_law chunks have NULL/empty hub_type!")

# ---------------------------------------------------------------------------
# 2d. Sample chunks from each hub
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("2d: SAMPLE CHUNKS FROM EACH HUB")
print("-" * 70)

for hub in ["legislation", "judicial_precedent", "advisory_opinion"]:
    chunks = DocumentChunk.objects.filter(
        document__document_type="reference_law",
        hub_type=hub,
        embedding__isnull=False,
    )[:3]
    if chunks:
        print(f"\n  Hub: {hub} — {len(chunks)} sample chunks:")
        for c in chunks:
            print(f"    doc={c.document.title} idx={c.chunk_index}")
            print(f"    content: {c.content[:200]}")
            print(f"    legal_context: {c.legal_context}")
    else:
        print(f"\n  Hub: {hub} — NO chunks found (or none with embeddings)")

# ---------------------------------------------------------------------------
# 2e. Check user_upload documents too (in case data was imported as user_upload)
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("2e: CHECK USER_UPLOAD DOCUMENTS FOR MILITARY CONTENT")
print("-" * 70)

user_docs = Document.objects.filter(document_type="user_upload").values(
    "id", "title", "status"
)
for d in user_docs:
    # Check if any chunk in this doc has military-related content
    for term in ["سرباز", "نیروهای مسلح", "فرار از خدمت", "مشمول", "نظامی"]:
        match = DocumentChunk.objects.filter(
            document_id=d["id"],
            content__icontains=term,
        ).first()
        if match:
            print(f"\n  ✓ Document '{d['title']}' has '{term}' in chunk {match.chunk_index}")
            print(f"    preview: {match.content[:150]}")
            break

print("\n" + "=" * 70)
print("STEP 2 COMPLETE")
print("=" * 70)
