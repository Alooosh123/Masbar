from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

bearer = HTTPBearer(auto_error=False)
ROLES = {"owner", "manager", "engineer", "technician", "viewer"}
PASSWORD_ITERATIONS = 310_000


class AuthStore:
    """Small SQLite identity store. Passwords are PBKDF2 hashes, never plaintext."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _password(password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
        )
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_first_owner(
        self, *, email: str, full_name: str, password: str, setup_token: str,
        expected_setup_token: str | None
    ) -> dict[str, Any]:
        if not expected_setup_token or not hmac.compare_digest(
            setup_token, expected_setup_token
        ):
            raise ValueError("invalid_setup_token")
        if len(password) < 12:
            raise ValueError("password_too_short")
        normalized_email = email.strip().lower()
        if len(normalized_email) < 5 or "@" not in normalized_email:
            raise ValueError("invalid_email")
        salt = secrets.token_bytes(16)
        user = {
            "id": secrets.token_urlsafe(18),
            "email": normalized_email,
            "full_name": full_name.strip(),
            "password_salt": base64.urlsafe_b64encode(salt).decode("ascii"),
            "password_hash": self._password(password, salt),
            "role": "owner",
            "created_at": int(time.time()),
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]) != 0:
                raise ValueError("already_initialized")
            db.execute(
                """
                INSERT INTO users(id,email,full_name,password_salt,password_hash,role,created_at)
                VALUES(:id,:email,:full_name,:password_salt,:password_hash,:role,:created_at)
                """,
                user,
            )
        return self.public_user(user)

    def create_user(self, *, email: str, full_name: str, password: str, role: str) -> dict[str, Any]:
        if role not in ROLES or role == "owner":
            raise ValueError("invalid_role")
        if len(password) < 12:
            raise ValueError("password_too_short")
        salt = secrets.token_bytes(16)
        user = {
            "id": secrets.token_urlsafe(18),
            "email": email.strip().lower(),
            "full_name": full_name.strip(),
            "password_salt": base64.urlsafe_b64encode(salt).decode("ascii"),
            "password_hash": self._password(password, salt),
            "role": role,
            "created_at": int(time.time()),
        }
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO users(id,email,full_name,password_salt,password_hash,role,created_at)
                    VALUES(:id,:email,:full_name,:password_salt,:password_hash,:role,:created_at)
                    """,
                    user,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("email_already_exists") from exc
        return self.public_user(user)

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE email=? COLLATE NOCASE AND disabled=0",
                (email.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        salt = base64.urlsafe_b64decode(row["password_salt"] + "==")
        expected = self._password(password, salt)
        if not hmac.compare_digest(expected, row["password_hash"]):
            return None
        return self.public_user(dict(row))

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def issue_token(user: dict[str, Any]) -> str:
    settings = get_settings()
    if not settings.auth_token_secret or len(settings.auth_token_secret) < 32:
        raise RuntimeError("AUTH_TOKEN_SECRET must contain at least 32 characters")
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {
                "sub": user["id"],
                "email": user["email"],
                "name": user["full_name"],
                "role": user["role"],
                "iat": now,
                "exp": now + settings.auth_token_ttl_hours * 3600,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(
        settings.auth_token_secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def user_from_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.auth_token_secret:
        return None
    try:
        header, payload, signature = token.split(".")
        signing_input = f"{header}.{payload}".encode("ascii")
        expected = hmac.new(
            settings.auth_token_secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        actual = base64.urlsafe_b64decode(signature + "===")
        if not hmac.compare_digest(expected, actual):
            return None
        claims = json.loads(base64.urlsafe_b64decode(payload + "==="))
        if claims.get("exp", 0) <= int(time.time()):
            return None
        if claims.get("role") not in ROLES or not claims.get("sub"):
            return None
        return {
            "id": claims["sub"],
            "email": claims.get("email", ""),
            "full_name": claims.get("name", ""),
            "role": claims["role"],
        }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def get_auth_store() -> AuthStore:
    settings = get_settings()
    return AuthStore(settings.auth_db_path)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message_ar": "سجّل الدخول للمتابعة."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_from_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_or_expired_token", "message_ar": "انتهت الجلسة أو رمز الدخول غير صالح. سجّل الدخول مجددًا."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed_roles: str):
    def dependency(user: dict[str, Any] | None = Depends(get_current_user)):
        if user is None and not get_settings().auth_enabled:
            return None
        if user is None or user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "insufficient_role", "message_ar": "لا تملك صلاحية تنفيذ هذا الإجراء."},
            )
        return user
    return dependency
