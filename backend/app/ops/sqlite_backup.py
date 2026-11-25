from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKUP_PATTERN = re.compile(r"^masbar-sqlite-(\d{8}T\d{6}Z)\.sqlite3$")


@dataclass(frozen=True)
class BackupResult:
    backup_path: str
    manifest_path: str
    created_at: str
    size_bytes: int
    sha256: str
    integrity_check: str
    tables: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_database(path: Path) -> tuple[str, list[str]]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=15)
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity = "; ".join(str(row[0]) for row in integrity_rows)
        if integrity.lower() != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return integrity, tables
    finally:
        connection.close()


def create_sqlite_backup(database_path: Path | str, destination_dir: Path | str) -> BackupResult:
    """Create and verify a consistent SQLite snapshot, including committed WAL data."""
    source = Path(database_path).expanduser().resolve()
    destination = Path(destination_dir).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {source}")
    if source == destination or source.is_relative_to(destination):
        raise ValueError("Backup destination must not contain the source database")

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    created = datetime.now(timezone.utc)
    stamp = created.strftime("%Y%m%dT%H%M%SZ")
    final_path = destination / f"masbar-sqlite-{stamp}.sqlite3"
    manifest_path = destination / f"masbar-sqlite-{stamp}.manifest.json"

    fd, temp_name = tempfile.mkstemp(prefix=".masbar-backup-", suffix=".sqlite3.tmp", dir=destination)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
        target_connection = sqlite3.connect(temp_path, timeout=30)
        try:
            source_connection.backup(target_connection, pages=256, sleep=0.05)
            target_connection.commit()
        finally:
            target_connection.close()
            source_connection.close()

        integrity, tables = _check_database(temp_path)
        size_bytes = temp_path.stat().st_size
        digest = _sha256(temp_path)
        os.replace(temp_path, final_path)

        result = BackupResult(
            backup_path=str(final_path),
            manifest_path=str(manifest_path),
            created_at=created.isoformat(),
            size_bytes=size_bytes,
            sha256=digest,
            integrity_check=integrity,
            tables=tables,
        )
        manifest_tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        manifest_tmp.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_tmp, 0o600)
        os.replace(manifest_tmp, manifest_path)
        return result
    except Exception:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise


def prune_sqlite_backups(destination_dir: Path | str, retention_days: int, *, now: datetime | None = None) -> list[str]:
    """Delete only this tool's recognized backup files older than retention_days."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    destination = Path(destination_dir).expanduser().resolve()
    if not destination.exists():
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    removed: list[str] = []
    for candidate in destination.iterdir():
        match = BACKUP_PATTERN.fullmatch(candidate.name)
        if not match or not candidate.is_file():
            continue
        timestamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if timestamp < cutoff:
            manifest = candidate.with_name(candidate.name.replace(".sqlite3", ".manifest.json"))
            candidate.unlink()
            manifest.unlink(missing_ok=True)
            removed.append(candidate.name)
    return removed


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create and verify a consistent SQLite backup for Masbar.")
    parser.add_argument("--database", default=os.environ.get("SESSION_DB_PATH", "/app/data/sessions/sessions.sqlite3"))
    parser.add_argument("--destination", default=os.environ.get("SQLITE_BACKUP_DIR", "/app/data/sessions/backups"))
    parser.add_argument("--retention-days", type=int, default=int(os.environ.get("SQLITE_BACKUP_RETENTION_DAYS", "14")))
    args = parser.parse_args()

    result = create_sqlite_backup(args.database, args.destination)
    removed = prune_sqlite_backups(args.destination, args.retention_days)
    print(json.dumps({"backup": asdict(result), "removed_old_backups": removed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
