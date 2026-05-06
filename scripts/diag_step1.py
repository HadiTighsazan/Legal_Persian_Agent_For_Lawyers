"""Diagnostic Step 1: Check document 30 chunks."""
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from documents.models import Document, DocumentChunk

doc = Document.objects.get(title='30')
print(f'Document: id={doc.id} title={doc.title} status={doc.status} document_type={doc.document_type} total_chunks={doc.total_chunks}')
chunk_count = DocumentChunk.objects.filter(document_id=doc.id).count()
embedded_count = DocumentChunk.objects.filter(document_id=doc.id, embedding__isnull=False).count()
print(f'Total chunks: {chunk_count}')
print(f'Embedded chunks: {embedded_count}')

# Check if 'غصب' exists
sample = DocumentChunk.objects.filter(document_id=doc.id, content__icontains='\u063a\u0635\u0628').first()
if sample:
    print(f'FOUND chunk with ghasb: index={sample.chunk_index}')
    print(f'Has embedding: {sample.embedding is not None}')
    print(f'Content: {sample.content[:500]}')
    meta = dict(sample.metadata) if sample.metadata else {}
    print(f'Metadata: {meta}')
else:
    print('NO chunk contains ghasb')
    # Show first 5 chunks
    for c in DocumentChunk.objects.filter(document_id=doc.id)[:5]:
        print(f'Chunk {c.chunk_index}: {c.content[:200]}')
