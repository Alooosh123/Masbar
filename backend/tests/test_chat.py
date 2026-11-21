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


def test_torque_is_blocked_before_loto_in_chat(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    identified = _chat(client, "حدد القطعة 312-5620", session_id=session_id)

    blocked = _chat(client, "كم العزم؟", session_id=session_id)
    assert blocked["session"]["state"] == "AWAITING_LOTO"
    assert "بوابة السلامة" in blocked["message_ar"]

    ids = [item["id"] for item in identified["session"]["safety_lockout"]["checklist"]]
    loto = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": ids},
    )
    assert loto.status_code == 200

    torque = _chat(client, "كم العزم؟", session_id=session_id)
    assert "45" in torque["message_ar"]
    assert "SENR9834-08" in torque["message_ar"]


def test_next_step_from_chat_after_loto(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    identified = _chat(client, "312-5620", session_id=session_id)
    ids = [item["id"] for item in identified["session"]["safety_lockout"]["checklist"]]
    client.post(f"/api/v1/sessions/{session_id}/loto", json={"confirmed_item_ids": ids})

    body = _chat(client, "الخطوة التالية", session_id=session_id)
    assert body["session"]["current_step"]["step_number"] == 2
    assert body["session"]["state"] == "IN_PROGRESS"


def test_safety_question_without_session_never_calls_llm(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "كم عزم صمام 312-5620؟")
    assert body["source"] == "system"
    assert "قاعدة المعرفة" in body["message_ar"]
    assert fake.calls == []


def test_voice_loto_confirmation_is_rejected(client):
    start = _chat(client, "ابدأ جلسة على C15")
    session_id = start["session"]["session_id"]
    _chat(client, "حدد القطعة 312-5620", session_id=session_id)

    body = _chat(client, "تم العزل", session_id=session_id)
    assert "التأكيد الصوتي وحده" in body["message_ar"]
    assert body["session"]["state"] == "AWAITING_LOTO"


def test_general_chat_uses_adapter(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "كيف تعمل المضخة الهيدروليكية؟")
    assert body["source"] == "general"
    assert body["message_ar"] == "هذه إجابة عامة تجريبية."
    assert len(fake.calls) == 1
    assert fake.calls[0]["describe"] is False


def test_image_defaults_to_description_not_identification(client, monkeypatch):
    fake = _use_fake_chat(monkeypatch)
    body = _chat(client, "", image_base64="AA==")
    assert body["source"] == "vision"
    assert "وصف عام" in body["message_ar"]
    assert fake.calls[0]["describe"] is True
    assert fake.calls[0]["image_base64"] == "AA=="
    assert body["session"] is None
    # Camera commands in the chat history must not bias the description.
    assert fake.calls[0]["history"] == []
    assert fake.calls[0]["context"] is None


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
