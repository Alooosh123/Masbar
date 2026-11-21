from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
    """In-memory session store for Milestone 1 (swap for Redis in production)."""

    def __init__(self, ttl_minutes: int = 240):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._ttl = timedelta(minutes=ttl_minutes)

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
                del self._sessions[session_id]
                raise SessionNotFound(session_id)

            session.touch()
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
        return entry

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
