from .document_processing import chunk_document, embed_document, extract_text_from_pdf

# process_document is a regular Python function (not a Celery task) that has
# been moved to documents.services.processing_service. It is re-exported here
# for backward compatibility so that existing imports (e.g. from views) continue
# to work without modification.
from documents.services.processing_service import process_document  # noqa: PLC0415

__all__ = ["extract_text_from_pdf", "chunk_document", "embed_document", "process_document"]
