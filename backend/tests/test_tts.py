from __future__ import annotations

import asyncio

from app.adapters.tts.edge import ARABIC_VOICES, DEFAULT_ARABIC_VOICE, EdgeTtsAdapter


class FakeCommunicate:
    def __init__(self, text: str, voice: str) -> None:
        self.text = text
        self.voice = voice

    async def stream(self):
        yield {"type": "audio", "data": b"ID3\x04fake-mp3"}
        yield {"type": "WordBoundary", "offset": 0}


def test_tts_voices_are_all_arabic(client):
    response = client.get("/api/v1/tts/voices")
    assert response.status_code == 200
    body = response.json()
    assert body["default"].startswith("ar-")
    assert body["voices"]
    assert all(item["id"].startswith("ar-") for item in body["voices"])
    assert set(item["id"] for item in body["voices"]) == set(ARABIC_VOICES)


def test_tts_returns_arabic_audio(client, monkeypatch):
    monkeypatch.setattr("app.adapters.tts.edge.edge_tts.Communicate", FakeCommunicate)

    response = client.post("/api/v1/tts", json={"text": "مرحبًا، هذا اختبار الصوت العربي."})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-tts-language"] == "ar"
    assert response.headers["x-tts-voice"] == "ar-SA-ZariyahNeural"
    assert response.content == b"ID3\x04fake-mp3"


def test_tts_rejects_english_voice(client):
    response = client.post(
        "/api/v1/tts",
        json={"text": "hello", "voice": "en-US-JennyNeural"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "tts_unavailable"


def test_tts_rejects_empty_text(client):
    response = client.post("/api/v1/tts", json={"text": ""})
    assert response.status_code == 422


def test_tts_rejects_overlong_text(client):
    response = client.post("/api/v1/tts", json={"text": "ا" * 1201})
    assert response.status_code == 422


def test_tts_uses_disk_cache_when_service_unavailable(tmp_path, monkeypatch):
    text = "مرحبًا بك في مساعد المصنع. هذا اختبار للصوت العربي."
    key = EdgeTtsAdapter._cache_key(text, DEFAULT_ARABIC_VOICE)
    (tmp_path / f"{key}.mp3").write_bytes(b"ID3cached-audio")

    async def boom(self, text, voice):  # noqa: ARG001
        raise RuntimeError("network down")

    monkeypatch.setattr(EdgeTtsAdapter, "_collect", boom)
    adapter = EdgeTtsAdapter(cache_dir=tmp_path)

    result = asyncio.run(adapter.synthesize(text))

    assert result.audio == b"ID3cached-audio"
    assert result.mime_type == "audio/mpeg"
    assert result.voice == DEFAULT_ARABIC_VOICE


def test_tts_writes_audio_to_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("app.adapters.tts.edge.edge_tts.Communicate", FakeCommunicate)

    adapter = EdgeTtsAdapter(cache_dir=tmp_path)
    result = asyncio.run(adapter.synthesize("نص جديد يُحفظ في الذاكرة المحلية."))

    files = list(tmp_path.glob("*.mp3"))
    assert len(files) == 1
    assert files[0].read_bytes() == result.audio == b"ID3\x04fake-mp3"
