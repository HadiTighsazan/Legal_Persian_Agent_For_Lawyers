import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from documents.models import DocumentChunk
from django.conf import settings

chunk = DocumentChunk.objects.filter(embedding__isnull=False).first()
print(f'Actual embedding dimension in DB: {len(chunk.embedding)}')
print(f'Configured EMBEDDING_DIMENSION: {settings.EMBEDDING_DIMENSION}')
print(f'Match: {len(chunk.embedding) == settings.EMBEDDING_DIMENSION}')
