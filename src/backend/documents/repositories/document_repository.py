"""
Document repository module for database access operations.
"""
from typing import Optional

from django.core.paginator import EmptyPage, Paginator

from documents.models import Document


def create_document(
    user,
    filename: str,
    original_filename: str,
    file_size: int,
    mime_type: str,
    file_path: str,
    storage_type: str = "local",
) -> Document:
    """
    Create and return a new Document instance.

    Args:
        user: The User instance owning the document.
        filename: The stored filename (used as the document title).
        original_filename: The original uploaded filename.
        file_size: Size of the file in bytes.
        mime_type: MIME type of the file.
        file_path: Path where the file is stored.
        storage_type: Storage backend identifier (default: "local").

    Returns:
        The newly created Document instance.
    """
    document = Document.objects.create(
        user=user,
        title=filename,
        filename=filename,
        original_filename=original_filename,
        file_size=file_size,
        mime_type=mime_type,
        file_path=file_path,
        storage_type=storage_type,
    )
    return document


def get_document_by_id(document_id: str) -> Optional[Document]:
    """
    Retrieve a Document by its UUID primary key.

    Args:
        document_id: The UUID string or UUID instance of the document.

    Returns:
        The Document instance if found, otherwise None.
    """
    try:
        return Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return None


def get_user_documents(
    user,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """
    Return a paginated dictionary of documents belonging to a user.

    Args:
        user: The User instance whose documents to retrieve.
        page: The page number (1-indexed, default: 1).
        page_size: Number of documents per page (default: 10).

    Returns:
        A dictionary with the following keys:
            - results: list of Document instances for the current page.
            - total: total number of documents for the user.
            - page: the current page number.
            - page_size: the number of items per page.
            - total_pages: the total number of pages.
            - has_next: boolean indicating whether a next page exists.
            - has_previous: boolean indicating whether a previous page exists.
    """
    queryset = Document.objects.filter(user=user).order_by("-created_at")
    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages) if paginator.num_pages > 0 else []

    return {
        "results": list(page_obj.object_list),
        "total": paginator.count,
        "page": page_obj.number,
        "page_size": page_size,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }
