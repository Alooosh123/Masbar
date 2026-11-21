from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domain.api_models import AuditEntry
from app.domain.enums import IdentificationSource, SessionState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionNotFound(Exception):
    """Raised when a session id is unknown or expired."""


@dataclass
class Session:
    id: str
    equipment_model: str
    state: SessionState = SessionState.CREATED
    part_number: str | None = None
    identification_id: str | None = None
    confidence: float = 0.0
    bounding_box: tuple[float, float, float, float] | None = None
    identification_source: IdentificationSource | None = None
    loto_confirmed: bool = False
    confirmed_items: set[str] = field(default_factory=set)
    step_index: int = 1
    audit: list[AuditEntry] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()


class SessionStore:
    """TTL session store with optional SQLite persistence for a single app process.

    SQLite persistence is suitable for a single instance on one host. A
    multi-worker or multi-host deployment must use a shared transactional store.
    """

    def __init__(
        self,
        ttl_minutes: int = 240,
        db_path: Path | str | None = None,
    ):
        if ttl_minutes < 1:
            raise ValueError("ttl_minutes must be at least one")
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._ttl = timedelta(minutes=ttl_minutes)
        self._db_path = Path(db_path).expanduser().resolve() if db_path else None

        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize_db()
            self._restore_sessions()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("SQLite persistence is not configured")
        connection = sqlite3.connect(self._db_path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize_db(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at)"
            )

    @staticmethod
    def _serialize(session: Session) -> str:
        payload = {
            "id": session.id,
            "equipment_model": session.equipment_model,
            "state": session.state.value,
            "part_number": session.part_number,
            "identification_id": session.identification_id,
            "confidence": session.confidence,
            "bounding_box": list(session.bounding_box) if session.bounding_box else None,
            "identification_source": (
                session.identification_source.value
                if session.identification_source is not None
                else None
            ),
            "loto_confirmed": session.loto_confirmed,
            "confirmed_items": sorted(session.confirmed_items),
            "step_index": session.step_index,
            "audit": [entry.model_dump(mode="json") for entry in session.audit],
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _deserialize(payload: str) -> Session:
        data = json.loads(payload)
        box = data.get("bounding_box")
        source = data.get("identification_source")
        return Session(
            id=data["id"],
            equipment_model=data["equipment_model"],
            state=SessionState(data.get("state", SessionState.CREATED.value)),
            part_number=data.get("part_number"),
            identification_id=data.get("identification_id"),
            confidence=float(data.get("confidence", 0.0)),
            bounding_box=tuple(float(value) for value in box) if box else None,
            identification_source=IdentificationSource(source) if source else None,
            loto_confirmed=bool(data.get("loto_confirmed", False)),
            confirmed_items=set(data.get("confirmed_items", [])),
            step_index=int(data.get("step_index", 1)),
            audit=[AuditEntry.model_validate(item) for item in data.get("audit", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def _persist(self, session: Session) -> None:
        if self._db_path is None:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(id, updated_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (session.id, session.updated_at.isoformat(), self._serialize(session)),
            )

    def _delete_persisted(self, session_id: str) -> None:
        if self._db_path is None:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def _restore_sessions(self) -> None:
        if self._db_path is None:
            return
        now = utc_now()
        with self._connect() as connection:
            rows = connection.execute("SELECT id, payload FROM sessions").fetchall()
            expired_ids: list[str] = []
            for session_id, payload in rows:
                try:
                    session = self._deserialize(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"Stored session {session_id!r} is corrupt; refusing silent data loss"
                    ) from exc
                if now - session.updated_at > self._ttl:
                    expired_ids.append(session_id)
                else:
                    self._sessions[session_id] = session
            if expired_ids:
                connection.executemany(
                    "DELETE FROM sessions WHERE id = ?",
                    [(session_id,) for session_id in expired_ids],
                )

    def create(self, equipment_model: str) -> Session:
        with self._lock:
            session_id = f"mnt-{utc_now():%Y%m%d}-{secrets.token_hex(3)}"
            session = Session(id=session_id, equipment_model=equipment_model)
            self._sessions[session_id] = session
            self.audit(session, "session_created", f"بدأت جلسة صيانة لمعدة: {equipment_model}")
            return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)

            if utc_now() - session.updated_at > self._ttl:
                self._sessions.pop(session_id, None)
                self._delete_persisted(session_id)
                raise SessionNotFound(session_id)

            session.touch()
            self._persist(session)
            return session

    def audit(self, session: Session, event: str, detail_ar: str) -> AuditEntry:
        entry = AuditEntry(
            id=f"aud-{secrets.token_hex(4)}",
            timestamp=utc_now(),
            event=event,
            detail_ar=detail_ar,
        )
        session.audit.append(entry)
        session.touch()
        self._sessions[session.id] = session
        self._persist(session)
        return entry

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
