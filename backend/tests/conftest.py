import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app


@pytest.fixture(autouse=True)
def isolated_tts_cache(tmp_path, monkeypatch):
    """Keep synthetic test audio out of the real Arabic voice cache."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "tts-cache"))
    get_settings.cache_clear()
    reset_caches()
    yield
    reset_caches()
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
