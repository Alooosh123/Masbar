from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app


def _configure_auth(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-signing-secret-that-is-long-enough-32-bytes")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "Test-owner-password-2026-is-long")
    monkeypatch.setenv("CORS_ORIGINS", "http://testserver")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    reset_caches()


def test_sessions_require_login_and_bootstrapped_owner_can_create_session(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as client:
        denied = client.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert denied.status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "OWNER@example.test", "password": "Test-owner-password-2026-is-long"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "owner"
        assert "masbar_access" in client.cookies

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["authenticated"] is True

        created = client.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert created.status_code == 201
        assert created.json()["session_id"]


def test_admin_can_create_technician_but_technician_cannot_manage_users(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as owner_client:
        login = owner_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "Test-owner-password-2026-is-long"},
        )
        assert login.status_code == 200
        created = owner_client.post(
            "/api/v1/auth/users",
            json={
                "email": "tech@example.test",
                "display_name": "فني اختبار",
                "password": "Technician-password-2026-long",
                "role": "technician",
            },
        )
        assert created.status_code == 201
        assert created.json()["user"]["role"] == "technician"

    with TestClient(app) as technician_client:
        login = technician_client.post(
            "/api/v1/auth/login",
            json={"email": "tech@example.test", "password": "Technician-password-2026-long"},
        )
        assert login.status_code == 200
        assert technician_client.post(
            "/api/v1/auth/users",
            json={
                "email": "second-tech@example.test",
                "display_name": "فني ثان",
                "password": "Technician-password-2026-long",
                "role": "technician",
            },
        ).status_code == 403
        assert technician_client.get("/api/v1/auth/users").status_code == 403


def test_logout_removes_auth_cookie(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "Test-owner-password-2026-is-long"},
        )
        result = client.post("/api/v1/auth/logout")
        assert result.status_code == 200
        assert client.get("/api/v1/auth/me").json()["authenticated"] is False
