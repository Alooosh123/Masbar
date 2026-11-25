from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings

AUTH_COOKIE_NAME = "masbar_access"
AUTH_ISSUER = "masbar"
PASSWORD_ITERATIONS = 310_000
PASSWORD_MIN_LENGTH = 14
ALLOWED_ROLES = {"owner", "admin", "technician", "viewer"}


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: str
    last_login_at: str | None
    token_version: int

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("A valid email address is required")
        return normalized


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    display_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=256)
    role: str = Field(default="technician", pattern=r"^(admin|technician|viewer)$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return value.strip()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=256)


class AuthStore:
    """SQLite identity store colocated with sessions so one persistent volume protects both."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        auth_required: bool,
        bootstrap_email: str | None,
        bootstrap_password: str | None,
    ):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if auth_required:
            self._ensure_bootstrap_owner(bootstrap_email, bootstrap_password)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('owner','admin','technician','viewer')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT,
                    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT,
                    token_version INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    event TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_events_created_at ON auth_events(created_at)"
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_recovery_uses (
                    token_hash TEXT PRIMARY KEY,
                    used_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @classmethod
    def _hash_password(cls, password: str) -> str:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Passwords must contain at least {PASSWORD_MIN_LENGTH} characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS, dklen=32
        )
        return "pbkdf2_sha256$" + str(PASSWORD_ITERATIONS) + "$" + cls._encode(salt) + "$" + cls._encode(digest)

    @classmethod
    def _verify_password(cls, password: str, encoded: str) -> bool:
        try:
            algorithm, rounds, salt_text, digest_text = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(rounds)
            if iterations < 100_000 or iterations > 2_000_000:
                return False
            salt = cls._decode(salt_text)
            expected = cls._decode(digest_text)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _to_user(row: sqlite3.Row | None) -> AuthUser | None:
        if row is None:
            return None
        return AuthUser(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            token_version=int(row["token_version"]),
        )

    @staticmethod
    def _event(connection: sqlite3.Connection, user_id: str | None, event: str, details: str = "") -> None:
        connection.execute(
            "INSERT INTO auth_events(user_id,event,created_at,details) VALUES(?,?,?,?)",
            (user_id, event, datetime.now(timezone.utc).isoformat(), details[:300]),
        )

    def _ensure_bootstrap_owner(self, email: str | None, password: str | None) -> None:
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])
        if count:
            return
        if not email or not password:
            raise RuntimeError(
                "AUTH_REQUIRED is enabled but no user exists. Configure "
                "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD once to create the owner."
            )
        normalized_email = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
            raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL is not a valid email address")
        if len(password) < 20:
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 20 characters")
        self.create_user(
            email=normalized_email,
            display_name="مِسبار — المالك",
            password=password,
            role="owner",
            event="bootstrap_owner_created",
        )

    def reset_primary_owner_password_once(self, token: str, new_password: str) -> AuthUser | None:
        """Consume a one-time recovery token to rotate the existing primary owner's password."""
        if len(token) < 32:
            raise ValueError("OWNER_PASSWORD_RESET_TOKEN must contain at least 32 characters")
        if len(new_password) < 20:
            raise ValueError("OWNER_PASSWORD_RESET_PASSWORD must contain at least 20 characters")

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        password_hash = self._hash_password(new_password)
        with self._connect() as connection:
            used = connection.execute(
                "SELECT 1 FROM auth_recovery_uses WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if used is not None:
                return None

            owner = connection.execute(
                """
                SELECT id FROM auth_users
                WHERE role = 'owner' AND is_active = 1
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if owner is None:
                raise RuntimeError("Cannot reset the owner password: no active owner account exists")

            user_id = str(owner["id"])
            connection.execute(
                """
                UPDATE auth_users
                SET password_hash = ?, failed_login_attempts = 0, locked_until = NULL,
                    token_version = token_version + 1
                WHERE id = ?
                """,
                (password_hash, user_id),
            )
            self._event(connection, user_id, "owner_password_recovered", "one_time_environment_recovery")
            connection.execute(
                "INSERT INTO auth_recovery_uses(token_hash, used_at) VALUES(?, ?)",
                (token_hash, self._now().isoformat()),
            )

        return self.get_user(user_id)

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        role: str,
        event: str = "user_created",
    ) -> AuthUser:
        normalized_email = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
            raise ValueError("A valid email address is required")
        if role not in ALLOWED_ROLES:
            raise ValueError("Unsupported role")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Passwords must contain at least {PASSWORD_MIN_LENGTH} characters")

        user_id = "usr_" + secrets.token_urlsafe(18)
        created_at = self._now().isoformat()
        password_hash = self._hash_password(password)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO auth_users(
                        id,email,display_name,password_hash,role,is_active,created_at
                    ) VALUES(?,?,?,?,?,1,?)
                    """,
                    (user_id, normalized_email, display_name.strip(), password_hash, role, created_at),
                )
                self._event(connection, user_id, event, role)
        except sqlite3.IntegrityError as exc:
            raise ValueError("A user with this email already exists") from exc
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("User was not persisted")
        return user

    def get_user(self, user_id: str) -> AuthUser | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
        return self._to_user(row)

    def list_users(self) -> list[AuthUser]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM auth_users
                ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
                    WHEN 'technician' THEN 2 ELSE 3 END, email
                """
            ).fetchall()
        return [user for row in rows if (user := self._to_user(row)) is not None]

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        normalized_email = email.strip().casefold()
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE email=?", (normalized_email,)
            ).fetchone()
            user = self._to_user(row)
            if row is None or user is None or not user.is_active:
                self._event(connection, user.id if user else None, "login_failed")
                return None

            locked_until = row["locked_until"]
            if locked_until:
                try:
                    locked_time = datetime.fromisoformat(locked_until)
                except ValueError:
                    locked_time = now
                if locked_time > now:
                    self._event(connection, user.id, "login_blocked")
                    raise PermissionError("account_locked")

            if not self._verify_password(password, row["password_hash"]):
                attempts = int(row["failed_login_attempts"]) + 1
                lock_value = None
                if attempts >= 5:
                    lock_value = (now + timedelta(minutes=15)).isoformat()
                    attempts = 0
                connection.execute(
                    "UPDATE auth_users SET failed_login_attempts=?, locked_until=? WHERE id=?",
                    (attempts, lock_value, user.id),
                )
                self._event(connection, user.id, "login_failed")
                return None

            connection.execute(
                """
                UPDATE auth_users
                SET failed_login_attempts=0, locked_until=NULL, last_login_at=?
                WHERE id=?
                """,
                (now.isoformat(), user.id),
            )
            self._event(connection, user.id, "login_succeeded")
        return self.get_user(user.id)

    def change_password(self, user: AuthUser, current_password: str, new_password: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM auth_users WHERE id=?", (user.id,)
            ).fetchone()
            if row is None or not self._verify_password(current_password, row["password_hash"]):
                return False
            connection.execute(
                """
                UPDATE auth_users
                SET password_hash=?, failed_login_attempts=0, locked_until=NULL,
                    token_version=token_version+1
                WHERE id=?
                """,
                (self._hash_password(new_password), user.id),
            )
            self._event(connection, user.id, "password_changed")
        return True


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(user: AuthUser, secret: str, ttl_minutes: int) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url(
        json.dumps(
            {
                "iss": AUTH_ISSUER,
                "sub": user.id,
                "iat": now,
                "exp": now + ttl_minutes * 60,
                "ver": user.token_version,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = header + "." + payload
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return signing_input + "." + _b64url(signature)


def _token_claims(token: str, secret: str) -> dict | None:
    try:
        header_text, payload_text, signature_text = token.split(".", 2)
        header = json.loads(_b64url_decode(header_text))
        payload = json.loads(_b64url_decode(payload_text))
        if header != {"alg": "HS256", "typ": "JWT"}:
            return None
        signing_input = header_text + "." + payload_text
        expected = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_text)):
            return None
        now = int(datetime.now(timezone.utc).timestamp())
        if payload.get("iss") != AUTH_ISSUER:
            return None
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            return None
        if not isinstance(payload.get("iat"), int) or payload["iat"] > now + 60:
            return None
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= now:
            return None
        if not isinstance(payload.get("ver"), int):
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _store():
    from app.deps import get_auth_store
    return get_auth_store()


def resolve_access_token(token: str) -> AuthUser | None:
    settings = get_settings()
    if not settings.jwt_secret_key:
        return None
    claims = _token_claims(token, settings.jwt_secret_key)
    if claims is None:
        return None
    user = _store().get_user(claims["sub"])
    if user is None or not user.is_active or user.token_version != claims["ver"]:
        return None
    return user


def get_current_user(request: Request, *, required: bool = True) -> AuthUser | None:
    settings = get_settings()
    if not settings.auth_required:
        return None
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
    user = resolve_access_token(token) if token else None
    if user is None and required:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message_ar": "سجّل الدخول للمتابعة."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def websocket_user(websocket: WebSocket) -> AuthUser | None:
    settings = get_settings()
    if not settings.auth_required:
        return None
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    return resolve_access_token(token) if token else None


def origin_is_trusted(origin: str, allowed_origins: list[str]) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        candidate = parsed.scheme + "://" + parsed.netloc
        return candidate in allowed_origins
    except ValueError:
        return False
