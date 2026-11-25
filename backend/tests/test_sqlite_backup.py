import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ops.sqlite_backup import create_sqlite_backup, prune_sqlite_backups


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY, password_hash TEXT NOT NULL)")
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO auth_users VALUES ('owner-1', 'pbkdf2_hash_never_log')")
        connection.execute("INSERT INTO sessions VALUES ('session-1', '{\"state\":\"created\"}')")
        connection.commit()
    finally:
        connection.close()


def test_backup_is_consistent_and_restorable_with_wal_data(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_database(database)

    result = create_sqlite_backup(database, backup_dir)

    assert result.integrity_check == "ok"
    assert result.tables == ["auth_users", "sessions"]
    assert result.size_bytes > 0
    assert len(result.sha256) == 64
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["sha256"] == result.sha256

    restored_path = tmp_path / "restored.sqlite3"
    restored = sqlite3.connect(restored_path)
    source = sqlite3.connect(result.backup_path)
    try:
        source.backup(restored)
    finally:
        source.close()
        restored.close()

    check = sqlite3.connect(restored_path)
    try:
        assert check.execute("SELECT id FROM auth_users").fetchone() == ("owner-1",)
        assert check.execute("SELECT id FROM sessions").fetchone() == ("session-1",)
        assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        check.close()


def test_backup_rejects_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_sqlite_backup(tmp_path / "missing.sqlite3", tmp_path / "backups")


def test_backup_rejects_destination_containing_database(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    _create_database(database)
    with pytest.raises(ValueError):
        create_sqlite_backup(database, tmp_path)


def test_retention_removes_only_old_recognized_backups(tmp_path):
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    old_stamp = (now - timedelta(days=20)).strftime("%Y%m%dT%H%M%SZ")
    new_stamp = (now - timedelta(days=2)).strftime("%Y%m%dT%H%M%SZ")
    old = tmp_path / f"masbar-sqlite-{old_stamp}.sqlite3"
    old_manifest = tmp_path / f"masbar-sqlite-{old_stamp}.manifest.json"
    new = tmp_path / f"masbar-sqlite-{new_stamp}.sqlite3"
    unrelated = tmp_path / "keep-this.sqlite3"
    for path in (old, old_manifest, new, unrelated):
        path.write_text("test", encoding="utf-8")

    removed = prune_sqlite_backups(tmp_path, 14, now=now)

    assert removed == [old.name]
    assert not old.exists()
    assert not old_manifest.exists()
    assert new.exists()
    assert unrelated.exists()


def test_retention_requires_positive_days(tmp_path):
    with pytest.raises(ValueError):
        prune_sqlite_backups(tmp_path, 0)
