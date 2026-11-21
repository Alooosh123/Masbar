from __future__ import annotations


def _chat(client, message: str) -> dict:
    response = client.post("/api/v1/chat", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_reports_oem_registry_and_tts(client):
    body = client.get("/health").json()
    assert body["manufacturers"] == 31
    assert body["tts_ready"] is True
    assert body["tts_provider"] == "edge"


def test_manufacturer_registry_lists_real_brands(client):
    response = client.get("/api/v1/manufacturers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 31
    by_id = {item["id"]: item for item in body}
    assert by_id["caterpillar"]["name_ar"] == "كاتربيلر"
    assert by_id["komatsu"]["name_en"] == "Komatsu"
    assert by_id["volvo-ce"]["official_url"].startswith("https://www.volvoce.com")
    assert by_id["caterpillar"]["models_count"] >= 6
    assert "حفار هيدروليكي" in by_id["caterpillar"]["categories_ar"]


def test_manufacturer_search_by_model(client):
    response = client.get("/api/v1/manufacturers", params={"q": "PC200"})
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == ["komatsu"]


def test_manufacturer_detail_and_unknown(client):
    response = client.get("/api/v1/manufacturers/caterpillar")
    assert response.status_code == 200
    body = response.json()
    assert body["data_access"] == "subscription"
    assert any(model["model"] == "C15" for model in body["model_families"])
    assert str(body["official_url"]).startswith("https://www.cat.com")

    missing = client.get("/api/v1/manufacturers/not-a-real-brand")
    assert missing.status_code == 404


def test_chat_lists_manufacturers(client):
    body = _chat(client, "ما الشركات المتاحة؟")
    assert "كاتربيلر" in body["message_ar"]
    assert "كوماتسو" in body["message_ar"]
    assert "31" in body["message_ar"]
    assert "OEM" in body["message_ar"]


def test_chat_explains_real_data_limits(client):
    body = _chat(client, "هل البيانات حقيقية؟")
    assert "sample" in body["message_ar"]
    assert "كتيب خدمة OEM" in body["message_ar"]
    assert "source_page" in body["message_ar"]
