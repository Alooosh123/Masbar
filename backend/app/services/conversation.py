from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """Persistent, per-user conversation storage in the app's SQLite volume.

    Message text is stored for conversation continuity. Uploaded image bytes are
    deliberately not retained; only a boolean indicator is kept.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT 'محادثة جديدة',
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    source TEXT,
                    has_image INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(conversations)")
            }
            if "session_id" not in columns:
                connection.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated "
                "ON conversations(user_id, updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_messages_parent "
                "ON conversation_messages(conversation_id, id)"
            )

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"]),
            "preview": row["preview"] or "",
        }

    def create(self, user_id: str) -> dict[str, Any]:
        conversation_id = "conv_" + secrets.token_urlsafe(18)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id,user_id,title,session_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (conversation_id, user_id, "محادثة جديدة", None, now, now),
            )
        return {
            "id": conversation_id,
            "title": "محادثة جديدة",
            "session_id": None,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "preview": "",
        }

    def get_owned(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.id,c.title,c.session_id,c.created_at,c.updated_at,
                    (SELECT COUNT(*) FROM conversation_messages m WHERE m.conversation_id=c.id) AS message_count,
                    (SELECT content FROM conversation_messages m WHERE m.conversation_id=c.id
                     ORDER BY m.id DESC LIMIT 1) AS preview
                FROM conversations c WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self._summary(row) if row else None

    def list_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id,c.title,c.created_at,c.updated_at,
                    (SELECT COUNT(*) FROM conversation_messages m WHERE m.conversation_id=c.id) AS message_count,
                    (SELECT content FROM conversation_messages m WHERE m.conversation_id=c.id
                     ORDER BY m.id DESC LIMIT 1) AS preview
                FROM conversations c WHERE c.user_id=?
                ORDER BY c.updated_at DESC, c.id DESC LIMIT ?
                """,
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def set_session_id(
        self, user_id: str, conversation_id: str, session_id: str | None
    ) -> None:
        """Persist the backend-owned equipment session linked to a conversation."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET session_id=?, updated_at=? WHERE id=? AND user_id=?",
                (session_id, _now(), conversation_id, user_id),
            )
            if cursor.rowcount == 0:
                raise LookupError("Conversation not found")

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        *,
        source: str | None = None,
        has_image: bool = False,
    ) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Unsupported conversation message role")
        text = (content or "").strip()[:4000]
        if not text and not has_image:
            return
        if not text and has_image:
            text = "أرسل صورة في هذه الرسالة."
        now = _now()
        with self._connect() as connection:
            owned = connection.execute(
                "SELECT title FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if owned is None:
                raise LookupError("Conversation not found")
            connection.execute(
                """
                INSERT INTO conversation_messages(
                    conversation_id,role,content,source,has_image,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (conversation_id, role, text, source, int(has_image), now),
            )
            if role == "user" and owned["title"] == "محادثة جديدة":
                title = text.replace("\n", " ").strip()
                if len(title) > 72:
                    title = title[:69].rstrip() + "..."
                connection.execute(
                    "UPDATE conversations SET title=?,updated_at=? WHERE id=? AND user_id=?",
                    (title or "محادثة جديدة", now, conversation_id, user_id),
                )
            else:
                connection.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                    (now, conversation_id, user_id),
                )

    def messages_for_user(
        self, user_id: str, conversation_id: str, limit: int = 200
    ) -> list[dict[str, Any]] | None:
        with self._connect() as connection:
            owned = connection.execute(
                "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if owned is None:
                return None
            rows = connection.execute(
                """
                SELECT id,role,content,source,has_image,created_at
                FROM conversation_messages WHERE conversation_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (conversation_id, max(1, min(limit, 500))),
            ).fetchall()
        rows.reverse()
        return [
            {
                "id": int(row["id"]),
                "role": row["role"],
                "content": row["content"],
                "source": row["source"],
                "has_image": bool(row["has_image"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def history_for_model(
        self, user_id: str, conversation_id: str, limit: int = 12
    ) -> list[dict[str, str]] | None:
        messages = self.messages_for_user(user_id, conversation_id, limit=limit)
        if messages is None:
            return None
        return [{"role": item["role"], "content": item["content"]} for item in messages[-limit:]]

    def delete(self, user_id: str, conversation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            )
            return cursor.rowcount > 0
