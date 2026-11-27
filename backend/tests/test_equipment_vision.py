import asyncio
import base64
import json

from app.adapters.vision.equipment import EquipmentVisionAdapter


def test_equipment_vision_rejects_missing_invalid_and_oversized_images():
    adapter = EquipmentVisionAdapter(
        provider="cohere",
        api_key="test-key",
        base_url="https://api.cohere.com/v2",
        model="test-vision",
        max_image_bytes=4,
    )

    missing = asyncio.run(adapter.identify(None, ["Siemens S7-1200 Control Panel"]))
    invalid = asyncio.run(adapter.identify("not-base64", ["Siemens S7-1200 Control Panel"]))
    oversized = asyncio.run(
        adapter.identify(
            base64.b64encode(b"12345").decode("ascii"),
            ["Siemens S7-1200 Control Panel"],
        )
    )

    assert missing.error == "image_required"
    assert invalid.error == "invalid_or_oversized_image"
    assert oversized.error == "invalid_or_oversized_image"


def test_equipment_vision_uses_closed_catalog_and_validates_model_response(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "equipment_model": "Siemens S7-1200 Control Panel",
                                    "confidence": 0.94,
                                },
                            ),
                        }
                    ]
                }
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.adapters.vision.equipment.httpx.AsyncClient",
        FakeAsyncClient,
    )
    adapter = EquipmentVisionAdapter(
        provider="cohere",
        api_key="test-key",
        base_url="https://api.cohere.com/v2",
        model="test-vision",
    )
    image = base64.b64encode(b"fake-image").decode("ascii")

    result = asyncio.run(
        adapter.identify(
            image,
            [
                "Caterpillar C15 ACERT",
                "Siemens S7-1200 Control Panel",
            ],
        )
    )

    assert result.equipment_model == "Siemens S7-1200 Control Panel"
    assert result.confidence == 0.94
    assert "Caterpillar C15 ACERT" in captured["payload"]["messages"][1]["content"][0]["text"]
    assert captured["endpoint"] == "https://api.cohere.com/v2/chat"


def test_equipment_vision_rejects_model_outside_closed_catalog(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"equipment_model": "Unsupported excavator", "confidence": 0.99}
                            ),
                        }
                    ]
                }
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.adapters.vision.equipment.httpx.AsyncClient",
        FakeAsyncClient,
    )
    adapter = EquipmentVisionAdapter(
        provider="cohere",
        api_key="test-key",
        base_url="https://api.cohere.com/v2",
        model="test-vision",
    )
    image = base64.b64encode(b"fake-image").decode("ascii")

    result = asyncio.run(adapter.identify(image, ["Siemens S7-1200 Control Panel"]))

    assert result.equipment_model is None
    assert result.error == "unsupported_equipment_result"



def test_openrouter_equipment_identification_uses_openai_compatible_api(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "equipment_model": "Siemens S7-1200 Control Panel",
                            "confidence": 0.91,
                        })
                    }
                }]
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.adapters.vision.equipment.httpx.AsyncClient",
        FakeAsyncClient,
    )
    adapter = EquipmentVisionAdapter(
        provider="openrouter",
        api_key="test-openrouter-key",
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen3-vl-8b-instruct",
    )
    image = base64.b64encode(b"fake-image").decode("ascii")

    result = asyncio.run(
        adapter.identify(image, ["Siemens S7-1200 Control Panel"])
    )

    assert result.equipment_model == "Siemens S7-1200 Control Panel"
    assert result.provider == "openrouter:qwen/qwen3-vl-8b-instruct"
    assert captured["endpoint"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert captured["payload"]["model"] == "qwen/qwen3-vl-8b-instruct"
    assert captured["payload"]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
