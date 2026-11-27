import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.core.config import get_settings
from app.deps import get_manual_library, get_store
from app.domain.enums import SessionState
from app.services.session import SessionNotFound
from app.knowledge.manual_index import (
    MAX_PDF_BYTES,
    ManualDocumentSummary,
    ManualIndex,
    ManualIndexError,
    ManualSearchResponse,
    build_manual_index,
    write_manual_index,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["manuals"])


@router.get("/manuals", response_model=list[ManualDocumentSummary])
def list_manuals() -> list[ManualDocumentSummary]:
    """List only metadata for manuals indexed in the local runtime directory."""
    return get_manual_library().list_documents()


@router.get("/manuals/search", response_model=ManualSearchResponse)
def search_manuals(
    q: str = Query(min_length=2, max_length=500, description="Search text in Arabic or English"),
    session_id: str | None = Query(default=None, min_length=8, max_length=100),
    equipment_model: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=5, ge=1, le=20),
) -> ManualSearchResponse:
    """Search extracted manual text and return exact document/page citations.

    This is lexical retrieval, not vector retrieval, OCR, or authorization to
    execute a maintenance procedure.
    """
    if not get_settings().manual_search_available:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "manual_search_disabled",
                "message_ar": "بحث الكتيبات غير متاح. في الإنتاج يلزم MANUAL_SEARCH_ENABLED=true مع تفعيل AUTH_REQUIRED.",
            },
        )

    if not session_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "equipment_session_required",
                "message_ar": "يلزم تمرير جلسة معدة مؤكدة للبحث في دليلها.",
            },
        )

    try:
        session = get_store().get(session_id)
    except SessionNotFound:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "equipment_session_not_found",
                "message_ar": "جلسة المعدة غير موجودة أو انتهت صلاحيتها. أعد تحديد المعدة من الصورة.",
            },
        ) from None
    if session.state == SessionState.PENDING_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "equipment_confirmation_required",
                "message_ar": "أكد المعدة أولاً قبل البحث في دليل الصيانة.",
            },
        )
    if equipment_model and equipment_model != session.equipment_model:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "equipment_context_mismatch",
                "message_ar": "لا يمكن تغيير طراز المعدة داخل طلب البحث. ابدأ تحديداً جديداً من الصورة.",
            },
        )

    library = get_manual_library()
    hits = library.search(q, equipment_model=session.equipment_model, limit=limit)
    return ManualSearchResponse(
        query=q,
        equipment_model=session.equipment_model,
        retrieval_method="bm25_lexical",
        vector_search_enabled=False,
        hits=hits,
    )


@router.post("/manuals/ingest", status_code=201)
async def ingest_manual(
    request: Request,
    file: UploadFile = File(...),
    doc_id: str = Form(..., min_length=2, max_length=64),
    title: str = Form(..., min_length=3, max_length=240),
    manufacturer: str = Form(..., min_length=2, max_length=120),
    equipment_models: list[str] = Form(...),
    model_codes: list[str] = Form(default=[]),
    document_number: str | None = Form(default=None, max_length=120),
    revision: str | None = Form(default=None, max_length=80),
    language: str = Form(default="en", min_length=2, max_length=16),
    source_url: str | None = Form(default=None),
    rights_confirmed: bool = Form(default=False),
    rights_note: str = Form(default=""),
    overwrite: bool = Form(default=False),
) -> dict:
    """Ingest an OEM PDF into the private persistent index (owner/admin only).

    The original PDF is processed in a temporary directory and is not retained.
    Only the page-cited text index is written to MANUAL_INDEX_DIR.
    """
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "manual_ingestion_auth_required",
                "message_ar": "يجب تسجيل الدخول بحساب المالك أو المدير لاستيراد الكتيبات.",
            },
        )
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "manual_ingestion_forbidden",
                "message_ar": "استيراد الكتيبات متاح للمالك أو المدير فقط.",
            },
        )
    if not rights_confirmed or len(rights_note.strip()) < 8:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "manual_rights_confirmation_required",
                "message_ar": "أكد امتلاكك حق معالجة هذا الملف داخلياً، واكتب أساس الإذن أو الترخيص بوضوح.",
            },
        )
    if not any(value.strip() for value in equipment_models):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "manual_equipment_scope_required",
                "message_ar": "حدد طراز المعدة الدقيق المرتبط بهذا الكتيب.",
            },
        )

    raw_pdf = await file.read(MAX_PDF_BYTES + 1)
    await file.close()
    if len(raw_pdf) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "manual_pdf_too_large",
                "message_ar": "حجم ملف الكتيب يتجاوز الحد المسموح وهو 100 ميجابايت.",
            },
        )
    if not raw_pdf.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail={
                "code": "manual_pdf_invalid",
                "message_ar": "الملف المرفوع ليس ملف PDF صالحاً.",
            },
        )

    settings = get_settings()
    try:
        with tempfile.TemporaryDirectory(prefix="masbar-manual-") as temp_dir:
            pdf_path = Path(temp_dir) / "source.pdf"
            pdf_path.write_bytes(raw_pdf)
            index = await asyncio.to_thread(
                build_manual_index,
                pdf_path,
                doc_id=doc_id.strip(),
                title=title.strip(),
                manufacturer=manufacturer.strip(),
                equipment_models=[value.strip() for value in equipment_models if value.strip()],
                model_codes=[value.strip() for value in model_codes if value.strip()],
                document_number=document_number.strip() if document_number else None,
                revision=revision.strip() if revision else None,
                language=language.strip(),
                source_url=source_url.strip() if source_url else None,
                rights_confirmed=True,
                rights_note=rights_note.strip(),
            )
        await asyncio.to_thread(
            write_manual_index,
            index,
            settings.manual_index_dir,
            overwrite=overwrite,
        )
        get_manual_library.cache_clear()
        library = get_manual_library()
        document = next(
            item for item in library.list_documents() if item.doc_id == index.document.doc_id
        )
    except ManualIndexError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "manual_ingestion_rejected",
                "message_ar": str(exc),
            },
        ) from None
    except Exception:
        logger.exception("Manual ingestion failed")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "manual_ingestion_failed",
                "message_ar": "تعذر فهرسة الكتيب. راجع سجل الخادم دون مشاركة محتوى المستند.",
            },
        ) from None

    return {
        "document": document.model_dump(mode="json"),
        "chunks_created": len(index.chunks),
        "text_pages": index.document.text_pages,
        "pages_requiring_ocr": index.document.pages_requiring_ocr,
        "sha256": index.document.sha256,
        "original_pdf_retained": False,
        "retrieval_method": "bm25_lexical",
        "rag_generation": "cohere_when_configured",
    }



@router.post("/manuals/import-index", status_code=201)
async def import_manual_index(
    request: Request,
    file: UploadFile = File(...),
    overwrite: bool = Form(default=False),
) -> dict:
    """Import a prebuilt, schema-validated manual index (owner/admin only).

    This endpoint lets an owner upload a locally prepared index without
    transferring or retaining the original PDF on the application server.
    """
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "manual_ingestion_auth_required",
                "message_ar": "يجب تسجيل الدخول بحساب المالك أو المدير لاستيراد فهرس الكتيب.",
            },
        )
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "manual_ingestion_forbidden",
                "message_ar": "استيراد فهارس الكتيبات متاح للمالك أو المدير فقط.",
            },
        )

    max_index_bytes = 15 * 1024 * 1024
    raw_index = await file.read(max_index_bytes + 1)
    await file.close()
    if len(raw_index) > max_index_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "manual_index_too_large",
                "message_ar": "حجم ملف الفهرس يتجاوز الحد المسموح وهو 15 ميجابايت.",
            },
        )

    try:
        index = ManualIndex.model_validate_json(raw_index)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "manual_index_invalid",
                "message_ar": "ملف الفهرس غير صالح أو لا يطابق بنية مِسبار المعتمدة.",
            },
        ) from None

    if not index.document.rights_confirmed or len(index.document.rights_note.strip()) < 8:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "manual_rights_confirmation_required",
                "message_ar": "الفهرس لا يحتوي تأكيداً صالحاً لحق معالجة محتوى الكتيب.",
            },
        )

    settings = get_settings()
    try:
        await asyncio.to_thread(
            write_manual_index,
            index,
            settings.manual_index_dir,
            overwrite=overwrite,
        )
        get_manual_library.cache_clear()
        library = get_manual_library()
        document = next(
            item for item in library.list_documents() if item.doc_id == index.document.doc_id
        )
    except ManualIndexError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "manual_index_conflict",
                "message_ar": str(exc),
            },
        ) from None
    except Exception:
        logger.exception("Manual index import failed")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "manual_index_import_failed",
                "message_ar": "تعذر حفظ فهرس الكتيب. راجع سجل الخادم.",
            },
        ) from None

    return {
        "document": document.model_dump(mode="json"),
        "chunks_imported": len(index.chunks),
        "text_pages": index.document.text_pages,
        "pages_requiring_ocr": index.document.pages_requiring_ocr,
        "sha256": index.document.sha256,
        "original_pdf_transferred": False,
        "retrieval_method": "bm25_lexical",
    }
