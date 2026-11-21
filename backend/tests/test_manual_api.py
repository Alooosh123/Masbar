from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.domain.api_models import ChatRequest
from app.knowledge.manual_index import ManualChunk, ManualDocument, ManualIndex, write_manual_index
from app.main import app


def _seed_manual_index(index_dir):
    document = ManualDocument(
        doc_id="grundfos-cr5-test",
        title="Service instructions CR 1, CR 3 and CR 5",
        manufacturer="Grundfos",
        equipment_models=["Grundfos CR 5 Model A"],
        model_codes=["CR 5 Model A"],
        document_number="96546866 0407",
        revision="2007-04",
        language="en",
        source_url="https://www.grundfos.com/",
        sha256="b" * 64,
        page_count=19,
        text_pages=1,
        pages_requiring_ocr=18,
        indexed_at=datetime.now(timezone.utc),
        rights_confirmed=True,
        rights_note="Authorized synthetic test fixture",
    )
    chunks = [
        ManualChunk(
            chunk_id="3" * 64,
            doc_id=document.doc_id,
            pdf_page_number=9,
            printed_page_number=9,
            chunk_index=0,
            section_title="Replacement of shaft seal",
            text=(
                "Replacement of shaft seal. The shaft seal is identified as position "
                "105. Refer to the correct model and revision before any work."
            ),
        )
    ]
    write_manual_index(ManualIndex(document=document, chunks=chunks), index_dir)


def test_manual_list_and_search_api_return_source_metadata_and_page(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        documents = client.get("/api/v1/manuals")
        search = client.get(
            "/api/v1/manuals/search",
            params={"q": "shaft seal replacement", "equipment_model": "Grundfos CR 5 Model A"},
        )
        health = client.get("/health")

    assert documents.status_code == 200
    assert documents.json()[0]["document_number"] == "96546866 0407"
    assert search.status_code == 200
    body = search.json()
    assert body["retrieval_method"] == "bm25_lexical"
    assert body["vector_search_enabled"] is False
    assert body["hits"][0]["printed_page_number"] == 9
    assert body["hits"][0]["pdf_page_number"] == 9
    assert health.json()["manual_documents"] == 1
    assert health.json()["manual_chunks"] == 1


def test_chat_manual_search_returns_citation_not_a_generated_procedure(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن shaft seal"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "system"
    assert "96546866 0407" in body["message_ar"]
    assert "الصفحة المطبوعة 9" in body["message_ar"]
    assert "لا تنفذ خطوة صيانة" in body["message_ar"]
