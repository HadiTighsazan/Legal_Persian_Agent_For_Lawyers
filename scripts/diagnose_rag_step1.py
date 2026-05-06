"""Diagnostic Step 1: Check if chunks exist and contain the search terms."""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
import django
django.setup()

from documents.models import Document, DocumentChunk

# List all documents
print("=" * 60)
print("STEP 1: CHECK DOCUMENTS AND CHUNKS")
print("=" * 60)

docs = Document.objects.all().values("id", "title", "status", "document_type", "total_chunks")
for d in docs:
    print(f"\nDocument: {d}")
    chunk_count = DocumentChunk.objects.filter(document_id=d["id"]).count()
    embedded_count = DocumentChunk.objects.filter(document_id=d["id"], embedding__isnull=False).count()
    print(f"  Total chunks: {chunk_count}")
    print(f"  Embedded chunks: {embedded_count}")

    # Check if "November" exists in any chunk
    sample = DocumentChunk.objects.filter(document_id=d["id"], content__icontains="November").first()
    if sample:
        print(f'  ✓ Found chunk with "November": index={sample.chunk_index}')
        print(f"    Preview: {sample.content[:200]}")
    else:
        print(f'  ✗ NO chunk contains "November"')

    # Check if "1997" exists in any chunk
    sample2 = DocumentChunk.objects.filter(document_id=d["id"], content__icontains="1997").first()
    if sample2:
        print(f'  ✓ Found chunk with "1997": index={sample2.chunk_index}')
    else:
        print(f'  ✗ NO chunk contains "1997"')

print("\n" + "=" * 60)
print("STEP 1 COMPLETE")
print("=" * 60)
