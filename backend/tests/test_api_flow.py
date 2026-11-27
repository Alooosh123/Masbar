from app.main import app  # noqa: F401  (ensures app imports cleanly in tests)


def _create(client, equipment: str = "Caterpillar C15 ACERT") -> dict:
    response = client.post("/api/v1/sessions", json={"equipment_model": equipment})
    assert response.status_code == 201, response.text
    pending = response.json()
    confirmed = client.post(
        "/api/v1/chat",
        json={"message": "تأكيد المعدة", "session_id": pending["session_id"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return client.get(f"/api/v1/sessions/{pending['session_id']}").json()


def _identify(client, session_id: str, payload: dict | None = None) -> dict:
    response = client.post(
        f"/api/v1/sessions/{session_id}/identify", json=payload or {}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _checklist_ids(body: dict) -> list[str]:
    return [item["id"] for item in body["safety_lockout"]["checklist"]]


def test_health_reports_loaded_knowledge(client):
    body = client.get("/health").json()
    assert body["status"] == "online"
    assert body["components"] == 6
    assert body["equipment"] == 2


def test_unknown_equipment_is_rejected(client):
    response = client.post(
        "/api/v1/sessions", json={"equipment_model": "Unknown Machine"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_equipment"


def test_missing_image_abstains_without_identifying_a_component(client):
    body = _create(client)
    assert body["state"] == "CREATED"

    result = _identify(client, body["session_id"])
    assert result["state"] == "CREATED"
    assert result["identified_component"] is None
    assert result["requires_closer_inspection"] is True
    assert result["abstained"] is True
    assert result["procedure_available"] is False


def test_steps_are_blocked_until_loto_confirmed(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_identification"


def test_incomplete_loto_checklist_is_rejected(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": []},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_identification"

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["state"] == "CREATED"
    assert session["identified_component"] is None
    assert session["procedure_available"] is False


def test_voice_confirmation_cannot_bypass_loto(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/ask", json={"transcript": "تم العزل أكمل"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "CREATED"
    assert response.json()["abstained"] is True
    assert response.json()["identified_component"] is None

    blocked = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "no_identification"


def test_unverified_demo_blocks_entire_maintenance_flow(client):
    body = _create(client)
    session_id = body["session_id"]

    identified = _identify(client, session_id)
    assert identified["abstained"] is True
    assert identified["identified_component"] is None
    assert identified["procedure_available"] is False

    loto = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": []},
    )
    assert loto.status_code == 409
    assert loto.json()["detail"]["code"] == "no_identification"

    step = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert step.status_code == 409

    torque = client.post(
        f"/api/v1/sessions/{session_id}/ask",
        json={"transcript": "كم عزم الشد حقه؟"},
    ).json()
    assert torque["abstained"] is True
    assert "45" not in torque["assistant_message_ar"]

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["state"] == "CREATED"
    assert session["procedure_available"] is False
    assert session["current_step"] is None



def test_arabic_text_identification(client):
    body = _create(client)
    identified = _identify(
        client, body["session_id"], {"transcript": "هذا البلف يهرب ديزل"}
    )
    assert identified["identified_component"]["part_number"] == "312-5620"


def test_low_confidence_returns_inspection_prompt(client):
    body = _create(client)
    identified = _identify(
        client,
        body["session_id"],
        {"part_number": "312-5620", "visual_confidence": 0.42},
    )
    assert identified["requires_closer_inspection"] is True
    assert identified["identified_component"] is None
    assert identified["current_step"] is None


def test_safety_query_lists_warnings(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/ask", json={"transcript": "تحذيرات السلامة"}
    ).json()
    assert "حدد القطعة أولًا" in response["assistant_message_ar"]
    assert response["abstained"] is True
    assert "افصل مفتاح البطاريات" not in response["assistant_message_ar"]


def test_audit_records_rejected_attempts(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    client.post(f"/api/v1/sessions/{session_id}/step", json={"action": "next"})
    audit = client.get(f"/api/v1/sessions/{session_id}/audit").json()
    events = [entry["event"] for entry in audit["entries"]]
    assert "identification_started" in events
    assert "identification_no_input" in events
    assert "component_identified" not in events
