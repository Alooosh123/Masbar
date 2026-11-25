from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app


def _health_with_env(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_caches()
    try:
        with TestClient(app) as client:
            return client.get("/health").json()
    finally:
        reset_caches()
        get_settings.cache_clear()


def test_health_reports_cohere_vision_as_configured(monkeypatch):
    health = _health_with_env(
        monkeypatch,
        VISION_PROVIDER="cohere",
        COHERE_API_KEY="test-cohere-key",
        CHAT_PROVIDER="off",
    )

    assert health["vision_provider"] == "cohere"
    assert health["vision_ready"] is True


def test_health_reports_missing_vision_key(monkeypatch):
    health = _health_with_env(
        monkeypatch,
        VISION_PROVIDER="mock",
        COHERE_API_KEY="",
        CHAT_PROVIDER="off",
    )

    assert health["vision_provider"] == "mock"
    assert health["vision_ready"] is False
