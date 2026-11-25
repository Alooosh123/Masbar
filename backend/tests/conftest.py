import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app


@pytest.fixture(autouse=True)
def isolated_runtime_data(tmp_path, monkeypatch):
    """Keep session databases and generated test audio outside real runtime data."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "tts-cache"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "sessions.sqlite3"))\n    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.sqlite3"))\n    monkeypatch.setenv("AUTH_ENABLED", "false")\n    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-only-secret-that-is-long-enough-123456")\n    monkeypatch.setenv("AUTH_SETUP_TOKEN", "test-only-bootstrap-token-long-enough")
    get_settings.cache_clear()
    reset_caches()
    yield
    reset_caches()
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
