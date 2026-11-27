from app.main import app  # noqa: F401  (ensures app imports cleanly in tests)


def _create(client, equipment: str = "Caterpillar C15 ACERT") -> dict:
    response = client.post("/api/v1/sessions", json={"equipment_model": equipment})
    assert response.status_code == 201, response.text
    return response.json()


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


def test_demo_identification_opens_safety_gate_only(client):
    body = _create(client)
    assert body["state"] == "CREATED"

    identified = _identify(client, body["session_id"])
    assert identified["state"] == "AWAITING_LOTO"
    assert identified["identified_component"]["part_number"] == "312-5620"
    assert identified["current_step"] is None
    assert identified["safety_lockout"]["loto_required"] is True
    assert identified["safety_lockout"]["source_status"] == "unverified"
    assert identified["safety_lockout"]["checklist"] == []
    assert identified["procedure_available"] is False


def test_steps_are_blocked_until_loto_confirmed(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "loto_required"


def test_incomplete_loto_checklist_is_rejected(client):
    body = _create(client)
    session_id = body["session_id"]
    identified = _identify(client, session_id)
    ids = _checklist_ids(identified)

    response = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": ids[:1]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "safety_not_verified"

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["state"] == "AWAITING_LOTO"
    assert session["current_step"] is None
    assert session["procedure_available"] is False


def test_voice_confirmation_cannot_bypass_loto(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/ask", json={"transcript": "تم العزل أكمل"}
    )
    assert response.status_code == 200
    assert "غير معتمدة" in response.json()["assistant_message_ar"]
    assert response.json()["state"] == "AWAITING_LOTO"
    assert response.json()["abstained"] is True

    blocked = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert blocked.status_code == 409


def test_unverified_demo_blocks_entire_maintenance_flow(client):
    body = _create(client)
    session_id = body["session_id"]

    identified = _identify(client, session_id)
    assert identified["procedure_available"] is False
    assert identified["current_step"] is None

    loto = client.post(
        f"/api/v1/sessions/{session_id}/loto",
        json={"confirmed_item_ids": _checklist_ids(identified)},
    )
    assert loto.status_code == 409
    assert loto.json()["detail"]["code"] == "safety_not_verified"

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
    assert session["state"] == "AWAITING_LOTO"
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
    assert "لا توجد تحذيرات أو إجراءات عزل موثقة ومعتمدة" in response["assistant_message_ar"]
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
    assert "component_identified" in events
