from __future__ import annotations

from app.adapters.chat.cohere_chat import ChatReply
from app.deps import get_chat_service
from app.main import app  # noqa: F401  (imports the FastAPI application)


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def reply(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        context: str | None = None,
        manual_context: str | None = None,
        image_base64: str | None = None,
        describe: bool = False,
    ) -> ChatReply:
        self.calls.append(
            {
                "message": message,
                "history": history or [],
                "context": context,
                "manual_context": manual_context,
                "image_base64": image_base64,
                "describe": describe,
            }
        )
        return ChatReply(text="هذه إجابة عامة تجريبية.", provider="fake")


def _chat(client, message: str = "", **extra) -> dict:
    response = client.post("/api/v1/chat", json={"message": message, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _use_fake_chat(monkeypatch) -> FakeChat:
    fake = FakeChat()
    monkeypatch.setattr(get_chat_service(), "chat", fake)
    return fake


def test_welcome_lists_equipment_and_quick_replies(client):
    body = _chat(client)
    assert body["source"] == "system"
    assert len(body["equipment"]) == 2
    assert any("افتح الكاميرا" in reply for reply in body["quick_replies"])
    assert "الكاميرا" in " ".join(body["quick_replies"])


def test_camera_and_microphone_actions(client):
    assert _chat(client, "افتح الكاميرا")["action"] == "open_camera"
    assert _chat(client, "أغلق الكاميرا")["action"] == "close_camera"
    assert _chat(client, "شغّل الميكروفون")["action"] == "start_listening"
    assert _chat(client, "أوقف الميكروفون")["action"] == "stop_listening"


def test_equipment_catalog_from_chat(client):
    body = _chat(client, "ما المعدات المتاحة؟")
    names = {item["equipment_family"] for item in body["equipment"]}
    assert names == {
        "Caterpillar C15 ACERT",
        "Siemens S7-1200 Control Panel",
    }


def test_manual_equipment_selection_cannot_start_a_session(client):
    body = _chat(client, "ابدأ جلسة على C15")
    assert body["session"] is None
    assert body["abstained"] is True
    assert body["action"] == "open_camera"
    assert "التقط صورة" in body["message_ar"]
def test_component_catalog_is_not_exposed_as_an_mvp_workflow(client):
    body = _chat(client, "اعرض القطع")
    assert body["abstained"] is True
    assert body["abstained"] is True
def test_part_number_selection_without_confirmed_equipment_abstains(client):
    body = _chat(client, "حدد القطعة 312-5620")
    assert body["session"] is None
    assert body["abstained"] is True
def test_maintenance_question_without_equipment_context_abstains(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "كم العزم؟")
    assert body["abstained"] is True
    assert "معدة" in body["abstention_reason_ar"]
    assert fake.calls == []
def test_step_commands_are_outside_the_mvp_chat_flow(client):
    body = _chat(client, "الخطوة التالية")
    assert body["session"] is None
    assert body["abstained"] is True
def test_safety_question_without_session_never_calls_llm(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "كم عزم صمام 312-5620؟")
    assert body["source"] == "system"
    assert "معدة" in body["message_ar"]
    assert body["abstained"] is True
    assert fake.calls == []


def test_voice_loto_confirmation_without_session_abstains(client):
    body = _chat(client, "تم العزل")
    assert body["session"] is None
    assert body["abstained"] is True
def test_out_of_scope_general_chat_abstains(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "tell me a joke")
    assert body["source"] == "system"
    assert body["abstained"] is True
    assert "خارج نطاق" in body["message_ar"]
    assert fake.calls == []


def test_manual_search_disabled_abstains_with_authentication_guidance(client):
    body = _chat(client, "ابحث في الكتيبات عن shaft seal")
    assert body["abstained"] is True
    assert "المصادقة والصلاحيات" in body["message_ar"]


def test_image_defaults_to_identification_not_general_description(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "", image_base64="AA==")
    assert body["source"] == "system"
    assert len(body["equipment"]) == 2
    assert "التعرف البصري الحقيقي" in body["message_ar"]
    assert fake.calls == []


def test_maintenance_question_without_confirmed_equipment_abstains(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "low hydraulic oil level")
    assert body["abstained"] is True
    assert "معدة" in body["abstention_reason_ar"]
    assert len(body["equipment"]) == 2
    assert fake.calls == []


def test_maintenance_question_with_session_uses_manual_retrieval(client, monkeypatch):
    from app.deps import get_chat_service
    from app.domain.api_models import SessionCreateRequest

    service = get_chat_service()
    service.settings.manual_search_enabled = True
    service.settings.environment = "test"

    fake = _use_fake_chat(monkeypatch)
    start = _chat(client, "ابدأ جلسة على 320D")
    assert start["session"] is None
    assert start["abstained"] is True
    assert "320D غير مدعومة" in start["message_ar"]
    assert "المعدات المتاحة" in start["message_ar"]
    body = _chat(client, "low hydraulic oil level")
    assert body["abstained"] is True
    assert "معدة" in body["abstention_reason_ar"]
    assert fake.calls == []


def test_image_identification_does_not_fall_back_to_mock_provider(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "حدد المعدة من الصورة", image_base64="AA==", mode="identify")
    assert body["session"] is None
    assert body["abstained"] is True
    assert "المحاكاة" in body["message_ar"] or "غير مهيأ" in body["message_ar"]
    assert fake.calls == []
def test_mock_vision_never_claims_successful_image_identification(client):
    body = _chat(client, "حدد المعدة من الصورة", image_base64="AA==", mode="identify")
    assert body["abstained"] is True
    assert body["session"] is None
    assert "غير مهيأ" in body["message_ar"]
def test_manual_rag_without_valid_synthesis_abstains_instead_of_showing_raw_chunks(
    client, monkeypatch
):
    from types import SimpleNamespace
    import app.deps

    service = get_chat_service()
    service.settings.manual_search_enabled = True
    service.settings.environment = "test"
    fake = _use_fake_chat(monkeypatch)

    hit = SimpleNamespace(
        document_id="manual-1",
        title="Approved OEM Manual",
        manufacturer="Siemens",
        document_number="DOC-1",
        revision="A",
        pdf_page_number=12,
        printed_page_number=10,
        section_title="Pump maintenance",
        excerpt="SECRET RAW MANUAL EXCERPT MUST NOT BE SHOWN",
        source_url=None,
        score=3.2,
    )
    library = SimpleNamespace(documents={"manual-1": object()}, search=lambda *args, **kwargs: [hit])
    getter = lambda: library
    getter.cache_clear = lambda: None
    monkeypatch.setattr(app.deps, "get_manual_library", getter)

    session = service.assistant.create_session(
        SessionCreateRequest(equipment_model="Siemens S7-1200 Control Panel")
    ).model_dump()
    confirmed = _chat(client, "تأكيد المعدة", session_id=session["session_id"])
    assert confirmed["session"]["state"] == "CREATED"
    body = _chat(
        client,
        "ابحث في الكتيبات عن صيانة المضخة",
        session_id=session["session_id"],
    )

    assert body["abstained"] is True
    assert "SECRET RAW MANUAL EXCERPT MUST NOT BE SHOWN" not in body["message_ar"]
    assert fake.calls
    assert fake.calls[0]["manual_context"]
def test_chat_unhandled_provider_exception_returns_safe_service_error(client, monkeypatch):
    from app.api.routes import chat as chat_route

    class BrokenChatService:
        async def handle(self, request):
            raise RuntimeError("private provider stack trace")

    monkeypatch.setattr(chat_route, "get_chat_service", lambda: BrokenChatService())
    response = client.post("/api/v1/chat", json={"message": "مرحبا"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "chat_temporarily_unavailable"
    assert "private provider stack trace" not in response.text


def test_out_of_scope_request_does_not_expose_model_internal_text(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "اشرح معنى لوحة التحكم بشكل مبسط.")
    assert body["abstained"] is True
    assert "User asks" not in body["message_ar"]
    assert "We should respond" not in body["message_ar"]
    assert fake.calls == []


def test_part_number_questions_without_identified_component_abstain(client):
    body = _chat(client, "ما رقم القطعة؟")
    assert body["abstained"] is True
    assert "قاعدة المعرفة" not in body["message_ar"]
