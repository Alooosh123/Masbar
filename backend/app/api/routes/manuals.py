from fastapi import APIRouter, Query

from app.deps import get_manual_library
from app.domain.api_models import ManualSearchResponse
from app.knowledge.manual_index import ManualDocumentSummary

router = APIRouter(prefix="/api/v1", tags=["manuals"])


@router.get("/manuals", response_model=list[ManualDocumentSummary])
def list_manuals() -> list[ManualDocumentSummary]:
    """List only metadata for manuals indexed in the local runtime directory."""
    return get_manual_library().list_documents()


@router.get("/manuals/search", response_model=ManualSearchResponse)
def search_manuals(
    q: str = Query(min_length=2, max_length=500, description="Search text in Arabic or English"),
    equipment_model: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=5, ge=1, le=20),
) -> ManualSearchResponse:
    """Search extracted manual text and return exact document/page citations.

    This is lexical retrieval, not vector retrieval, OCR, or authorization to
    execute a maintenance procedure.
    """
    library = get_manual_library()
    hits = library.search(q, equipment_model=equipment_model, limit=limit)
    return ManualSearchResponse(
        query=q,
        equipment_model=equipment_model,
        retrieval_method="bm25_lexical",
        vector_search_enabled=False,
        hits=hits,
    )
