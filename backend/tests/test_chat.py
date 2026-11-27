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
        image_base64: str | None = None,
        describe: bool = False,
    ) -> ChatReply:
        self.calls.append(
            {
                "message": message,
                "history": history or [],
                "context": context,
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
    assert len(body["equipment"]) == 3
    assert any("ابدأ جلسة" in reply for reply in body["quick_replies"])
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
        "Caterpillar 320D Excavator",
        "Caterpillar C15 ACERT",
        "Siemens S7-1200 Control Panel",
    }


def test_start_session_from_arabic_message(client):
    body = _chat(client, "ابدأ جلسة على C15")
    assert body["session"] is not None
    assert body["session"]["equipment_model"] == "Caterpillar C15 ACERT"
    assert body["session"]["state"] == "CREATED"


def test_component_catalog_in_chat(client):
    start = _chat(client, "ابدأ جلسة على C15 طرمبة")
    session_id = start["session"]["session_id"]
    body = _chat(client, "اعرض القطع", session_id=session_id)
    part_numbers = {item["part_number"] for item in body["components"]}
    assert "312-5620" in part_numbers
    assert len(body["components"]) == 3


def test_identify_by_part_number_from_chat(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    body = _chat(client, "حدد القطعة 312-5620", session_id=session_id)
    assert body["session"]["state"] == "AWAITING_LOTO"
    assert body["session"]["identified_component"]["part_number"] == "312-5620"
    assert body["session"]["current_step"] is None
    assert body["session"]["procedure_available"] is False
    assert body["session"]["safety_lockout"]["source_status"] == "unverified"
    assert body["session"]["safety_lockout"]["checklist"] == []


def test_unverified_torque_and_loto_are_blocked_in_chat(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    identified = _chat(client, "حدد القطعة 312-5620", session_id=session_id)

    assert identified["session"]["procedure_available"] is False
    assert identified["session"]["safety_lockout"]["checklist"] == []

    blocked = _chat(client, "كم العزم؟", session_id=session_id)
    assert blocked["session"]["state"] == "AWAITING_LOTO"
    assert "إيقاف آمن" in blocked["message_ar"]
    assert "45" not in blocked["message_ar"]

    loto = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": []},
    )
    assert loto.status_code == 409
    assert loto.json()["detail"]["code"] == "safety_not_verified"

    torque = _chat(client, "كم العزم؟", session_id=session_id)
    assert "45" not in torque["message_ar"]
    assert torque["session"]["current_step"] is None
    assert torque["session"]["procedure_available"] is False



def test_next_step_from_chat_is_blocked_for_unverified_component(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    _chat(client, "312-5620", session_id=session_id)

    body = _chat(client, "الخطوة التالية", session_id=session_id)
    assert body["session"]["current_step"] is None
    assert body["session"]["procedure_available"] is False
    assert body["abstained"] is True



def test_safety_question_without_session_never_calls_llm(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "كم عزم صمام 312-5620؟")
    assert body["source"] == "system"
    assert "قاعدة المعرفة" in body["message_ar"]
    assert body["abstained"] is True
    assert fake.calls == []


def test_voice_loto_confirmation_is_rejected(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    _chat(client, "حدد القطعة 312-5620", session_id=session_id)

    body = _chat(client, "تم العزل", session_id=session_id)
    assert "غير معتمدة" in body["message_ar"]
    assert body["session"]["state"] == "AWAITING_LOTO"
    assert body["session"]["procedure_available"] is False
    assert body["abstained"] is True


def test_out_of_scope_general_chat_abstains(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "tell me a joke")
    assert body["source"] == "system"
    assert body["abstained"] is True
    assert "خارج نطاق" in body["message_ar"]
    assert fake.calls == []


def test_image_defaults_to_identification_not_general_description(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "", image_base64="AA==")
    assert body["source"] == "system"
    assert len(body["equipment"]) == 3
    assert "اختر المعدة" in body["message_ar"]
    assert fake.calls == []


def test_maintenance_question_without_confirmed_equipment_abstains(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "low hydraulic oil level")
    assert body["abstained"] is True
    assert "معدة" in body["abstention_reason_ar"]
    assert len(body["equipment"]) == 3
    assert fake.calls == []


def test_maintenance_question_with_session_uses_manual_retrieval(client, monkeypatch):
    from app.deps import get_chat_service
    from app.services.chat import ChatService

    service = get_chat_service()
    service.settings.manual_search_enabled = True
    service.settings.environment = "test"

    class EmptyManualLibrary:
        documents = [object()]

        def search(self, query, equipment_model=None, limit=5):
            assert equipment_model == "Caterpillar 320D Excavator"
            assert "oil" in query.lower() or "hydraulic" in query.lower()
            return []

    def fake_manual_library():
        return EmptyManualLibrary()

    fake_manual_library.cache_clear = lambda: None
    monkeypatch.setattr("app.deps.get_manual_library", fake_manual_library)
    fake = _use_fake_chat(monkeypatch)
    start = _chat(client, "ابدأ جلسة على 320D")
    session_id = start["session"]["session_id"]
    body = _chat(client, "low hydraulic oil level", session_id=session_id)
    assert body["abstained"] is True
    assert "لم أجد دليلاً" in body["message_ar"]
    assert fake.calls == []


def test_explicit_image_identification_uses_grounded_part(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]

    body = _chat(
        client,
        "حدد القطعة 312-5620",
        image_base64="AA==",
        mode="identify",
        session_id=session_id,
    )
    assert body["session"]["state"] == "AWAITING_LOTO"
    assert body["session"]["identified_component"]["part_number"] == "312-5620"
    assert fake.calls == []  # identification never goes through the LLM


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


def test_unverified_part_number_is_not_presented_as_oem_citation(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    _chat(client, "حدد القطعة 312-5620", session_id=session_id)
    body = _chat(client, "ما رقم القطعة؟", session_id=session_id)
    assert body["abstained"] is True
    assert "SENR9834-08" not in body["message_ar"]
    assert "تجريبي" in body["message_ar"]
