import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app


def test_startup_creates_verified_sqlite_snapshot_when_enabled(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite3"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("VISION_PROVIDER", "mock")
    monkeypatch.setenv("CHAT_PROVIDER", "off")
    monkeypatch.setenv("SQLITE_BACKUP_ON_STARTUP", "true")
    monkeypatch.setenv("SESSION_DB_PATH", str(database))
    monkeypatch.setenv("SQLITE_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("SQLITE_BACKUP_RETENTION_DAYS", "14")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app):
        pass

    backups = list(backup_dir.glob("masbar-sqlite-*.sqlite3"))
    manifests = list(backup_dir.glob("masbar-sqlite-*.manifest.json"))
    assert len(backups) == 1
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["integrity_check"] == "ok"
    assert manifest["size_bytes"] > 0
