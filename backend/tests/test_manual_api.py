from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.adapters.chat.cohere_chat import ChatReply
from app.core.config import get_settings
from app.deps import reset_caches
from app.knowledge.manual_index import ManualChunk, ManualDocument, ManualIndex, write_manual_index
from app.main import app


def _seed_manual_index(index_dir):
    document = ManualDocument(
        doc_id="siemens-s7-1200-test",
        title="S7-1200 System Manual Test Fixture",
        manufacturer="Siemens",
        equipment_models=["Siemens S7-1200 Control Panel"],
        model_codes=["S7-1200"],
        document_number="A5E-TEST-001",
        revision="TEST",
        language="en",
        source_url="https://www.siemens.com/",
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
            pdf_page_index=8,
            pdf_page_number=9,
            printed_page_number=9,
            chunk_index=0,
            section_title="CPU technical specifications",
            text=(
                "CPU 1214C technical specifications. The controller belongs to the "
                "SIMATIC S7-1200 family. Verify the exact model and revision before work."
            ),
        )
    ]
    write_manual_index(ManualIndex(document=document, chunks=chunks), index_dir)


def test_manual_list_and_search_api_return_source_metadata_and_page(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        documents = client.get("/api/v1/manuals")
        search = client.get(
            "/api/v1/manuals/search",
            params={"q": "CPU 1214C technical specifications", "equipment_model": "Siemens S7-1200 Control Panel"},
        )
        health = client.get("/health")

    assert documents.status_code == 200
    assert documents.json()[0]["document_number"] == "A5E-TEST-001"
    assert search.status_code == 200
    body = search.json()
    assert body["retrieval_method"] == "bm25_lexical"
    assert body["vector_search_enabled"] is False
    assert body["hits"][0]["pdf_page_index"] == 8
    assert body["hits"][0]["printed_page_number"] == 9
    assert body["hits"][0]["pdf_page_number"] == 9
    assert health.json()["manual_documents"] == 1
    assert health.json()["manual_chunks"] == 1


def test_chat_manual_search_returns_citation_not_a_generated_procedure(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setattr("app.deps.build_chat_adapter", lambda settings: None)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        session = client.post(
            "/api/v1/sessions", json={"equipment_model": "Siemens S7-1200 Control Panel"}
        ).json()
        response = client.post(
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن CPU 1214C", "session_id": session["session_id"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "system"
    assert body["abstained"] is True
    assert "خدمة صياغة الإجابة" in body["message_ar"]


def test_manual_search_is_disabled_by_default_without_authentication(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "false")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        search = client.get("/api/v1/manuals/search", params={"q": "shaft seal"})
        chat = client.post(
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن shaft seal"},
        )

    assert search.status_code == 404
    assert search.json()["detail"]["code"] == "manual_search_disabled"
    assert chat.status_code == 200
    assert "بحث الكتيبات معطل افتراضياً" in chat.json()["message_ar"]
    assert "المصادقة والصلاحيات" in chat.json()["message_ar"]

def test_manual_search_stays_disabled_in_production_even_if_flag_is_true(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example.test")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        search = client.get("/api/v1/manuals/search", params={"q": "shaft seal"})
        chat = client.post(
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن shaft seal"},
        )

    assert search.status_code == 404
    assert search.json()["detail"]["code"] == "manual_search_disabled"
    assert "بحث الكتيبات معطل افتراضياً" in chat.json()["message_ar"]

def test_manual_rag_passes_retrieved_sources_to_generation_and_appends_citations(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    captured = {}

    class FakeRagAdapter:
        async def reply(self, **kwargs):
            captured.update(kwargs)
            return ChatReply(
                text="يوضح الدليل أن CPU 1214C جزء من عائلة S7-1200. [S1]",
                provider="test",
            )

    monkeypatch.setattr("app.deps.build_chat_adapter", lambda settings: FakeRagAdapter())
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        session = client.post(
            "/api/v1/sessions", json={"equipment_model": "Siemens S7-1200 Control Panel"}
        ).json()
        session_id = session["session_id"]
        response = client.post(
            "/api/v1/chat",
            json={"message": "اسأل الكتيبات عن CPU 1214C technical specifications", "session_id": session_id},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "assistant"
    assert "[S1]" in body["message_ar"]
    assert "A5E-TEST-001" in body["message_ar"]
    assert "الصفحة المطبوعة 9" in body["message_ar"]
    assert "manual_context" in captured
    assert "CPU 1214C" in captured["manual_context"]
    assert captured["message"] == "CPU 1214C technical specifications"
    reset_caches()


def test_manual_rag_keeps_torque_requests_retrieval_only(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    captured = {"called": False}

    class FakeRagAdapter:
        async def reply(self, **kwargs):
            captured["called"] = True
            return ChatReply(text="لا ينبغي استدعائي.", provider="test")

    monkeypatch.setattr("app.deps.build_chat_adapter", lambda settings: FakeRagAdapter())
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        session = client.post(
            "/api/v1/sessions", json={"equipment_model": "Siemens S7-1200 Control Panel"}
        ).json()
        response = client.post(
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن CPU 1214C torque", "session_id": session["session_id"]},
        )

    assert response.status_code == 200
    assert response.json()["source"] == "system"
    assert response.json()["abstained"] is True
    assert "المقتطف:" not in response.json()["message_ar"]
    assert captured["called"] is True
    reset_caches()


def test_direct_manual_torque_question_uses_retrieval_only(tmp_path, monkeypatch):
    _seed_manual_index(tmp_path)
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    captured = {"called": False}

    class FakeRagAdapter:
        async def reply(self, **kwargs):
            captured["called"] = True
            return ChatReply(text="إجابة تشغيلية غير مسموحة.", provider="test")

    monkeypatch.setattr("app.deps.build_chat_adapter", lambda settings: FakeRagAdapter())
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        session = client.post(
            "/api/v1/sessions", json={"equipment_model": "Siemens S7-1200 Control Panel"}
        ).json()
        response = client.post(
            "/api/v1/chat",
            json={"message": "ما قيمة عزم CPU 1214C في الكتيب؟", "session_id": session["session_id"]},
        )

    assert response.status_code == 200
    assert response.json()["source"] == "system"
    assert response.json()["abstained"] is True
    assert "المقتطف:" not in response.json()["message_ar"]
    assert captured["called"] is True
    reset_caches()


def test_manual_index_import_requires_authenticated_owner_or_admin(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/manuals/import-index",
            files={"file": ("manual.json", b"{}", "application/json")},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "manual_ingestion_auth_required"


def test_manual_index_import_validates_schema_and_persists_searchable_chunks(tmp_path, monkeypatch):
    from app.security.auth import AuthUser

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _seed_manual_index(source_dir)
    index_bytes = (source_dir / "siemens-s7-1200-test.json").read_bytes()

    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example.test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-signing-secret-" + ("x" * 32))
    monkeypatch.setenv("MANUAL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("MANUAL_INDEX_DIR", str(target_dir))
    get_settings.cache_clear()
    reset_caches()
    monkeypatch.setattr("app.main.get_auth_store", lambda: None)
    monkeypatch.setattr(
        "app.main.get_current_user",
        lambda request, required=True: AuthUser(
            id="owner-test",
            email="owner@example.test",
            display_name="Owner Test",
            role="owner",
            is_active=True,
            created_at="2026-01-01T00:00:00+00:00",
            last_login_at=None,
            token_version=0,
            must_change_password=False,
        ),
    )

    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/manuals/import-index",
            files={"file": ("siemens-s7-1200-test.json", index_bytes, "application/json")},
        )
        listed = client.get("/api/v1/manuals")
        searched = client.get(
            "/api/v1/manuals/search",
            params={"q": "CPU 1214C", "equipment_model": "Siemens S7-1200 Control Panel"},
        )

    assert imported.status_code == 201
    assert imported.json()["chunks_imported"] == 1
    assert imported.json()["original_pdf_transferred"] is False
    assert (target_dir / "siemens-s7-1200-test.json").is_file()
    assert listed.status_code == 200
    assert listed.json()[0]["document_number"] == "A5E-TEST-001"
    assert searched.status_code == 200
    assert searched.json()["hits"][0]["pdf_page_number"] == 9

    reset_caches()


def test_manual_ingestion_requires_authenticated_owner_or_admin(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    reset_caches()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/manuals/ingest",
            data={
                "doc_id": "manual-upload-test",
                "title": "Test manual",
                "manufacturer": "Example OEM",
                "equipment_models": "Example model",
                "rights_confirmed": "true",
                "rights_note": "Authorized internal test licence",
            },
            files={"file": ("manual.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "manual_ingestion_auth_required"
