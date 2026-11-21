from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings\nfrom app.deps import get_manual_library
from app.knowledge.manual_index import ManualDocumentSummary, ManualSearchResponse

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
    if not get_settings().manual_search_enabled:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "manual_search_disabled",
                "message_ar": "بحث مقتطفات الكتيبات معطل افتراضياً. فعّله فقط في بيئة محلية/خاصة إلى أن تُضاف مصادقة وصلاحيات.",
            },
        )

    library = get_manual_library()
    hits = library.search(q, equipment_model=equipment_model, limit=limit)
    return ManualSearchResponse(
        query=q,
        equipment_model=equipment_model,
        retrieval_method="bm25_lexical",
        vector_search_enabled=False,
        hits=hits,
    )
