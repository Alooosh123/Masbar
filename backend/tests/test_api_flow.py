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
    assert body["components"] == 9
    assert body["equipment"] == 3


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
    assert all(not item["confirmed"] for item in identified["safety_lockout"]["checklist"])


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
    assert response.json()["detail"]["code"] == "incomplete_checklist"

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["state"] == "AWAITING_LOTO"
    assert session["current_step"] is None


def test_voice_confirmation_cannot_bypass_loto(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/ask", json={"transcript": "تم العزل أكمل"}
    )
    assert response.status_code == 200
    assert "التأكيد الصوتي وحده" in response.json()["assistant_message_ar"]
    assert response.json()["state"] == "AWAITING_LOTO"

    blocked = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    )
    assert blocked.status_code == 409


def test_full_maintenance_flow(client):
    body = _create(client)
    session_id = body["session_id"]

    identified = _identify(client, session_id)
    ids = _checklist_ids(identified)

    loto = client.post(
        f"/api/v1/sessions/{session_id}/loto", json={"confirmed_item_ids": ids}
    )
    assert loto.status_code == 200
    loto_body = loto.json()
    assert loto_body["state"] == "READY"
    assert loto_body["safety_lockout"]["acknowledged_by_technician"] is True
    assert loto_body["current_step"]["step_number"] == 1

    # Torque is available from step 1 even though step 1 itself needs no torque.
    torque = client.post(
        f"/api/v1/sessions/{session_id}/ask",
        json={"transcript": "كم عزم الشد حقه؟"},
    ).json()
    assert "45" in torque["assistant_message_ar"]
    assert "SENR9834-08" in torque["assistant_message_ar"]

    for expected in (2, 3, 4):
        response = client.post(
            f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
        )
        assert response.status_code == 200
        assert response.json()["current_step"]["step_number"] == expected

    torque_step = client.post(
        f"/api/v1/sessions/{session_id}/ask", json={"transcript": "كم العزم؟"}
    ).json()
    assert torque_step["current_step"]["torque_spec"]["value_nm"] == 45.0

    completed = client.post(
        f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
    ).json()
    assert completed["state"] == "COMPLETED"
    assert "تم إنجاز جميع الخطوات" in completed["assistant_message_ar"]

    audit = client.get(f"/api/v1/sessions/{session_id}/audit").json()
    events = [entry["event"] for entry in audit["entries"]]
    assert "component_identified" in events
    assert "loto_confirmed" in events
    assert "procedure_completed" in events


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
    assert "افصل مفتاح البطاريات" in response["assistant_message_ar"]
    assert "بوابة العزل ما زالت مغلقة" in response["assistant_message_ar"]


def test_audit_records_rejected_attempts(client):
    body = _create(client)
    session_id = body["session_id"]
    _identify(client, session_id)

    client.post(f"/api/v1/sessions/{session_id}/step", json={"action": "next"})
    audit = client.get(f"/api/v1/sessions/{session_id}/audit").json()
    events = [entry["event"] for entry in audit["entries"]]
    assert "identification_started" in events
    assert "component_identified" in events
