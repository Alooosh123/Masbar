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



def test_owner_can_create_customer_and_customer_can_chat_but_not_execute_maintenance_steps(monkeypatch):
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
                "email": "customer@example.test",
                "display_name": "عميل تجريبي",
                "password": "Customer-password-2026-is-strong",
                "role": "customer",
            },
        )
        assert created.status_code == 201
        assert created.json()["user"]["role"] == "customer"

        session = owner_client.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert session.status_code == 201
        session_id = session.json()["session_id"]

    with TestClient(app) as customer_client:
        login = customer_client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.test", "password": "Customer-password-2026-is-strong"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "customer"

        # Newly created customer accounts must replace the temporary password first.
        rotated = customer_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Customer-password-2026-is-strong",
                "new_password": "Customer-new-password-2026-is-strong",
            },
        )
        assert rotated.status_code == 200

        # Customers can open a session and inspect it after password rotation.
        created_session = customer_client.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert created_session.status_code == 201
        assert customer_client.get(
            f"/api/v1/sessions/{created_session.json()['session_id']}"
        ).status_code == 200

        # Customer accounts cannot confirm LOTO or advance field execution.
        assert customer_client.post(
            f"/api/v1/sessions/{session_id}/loto",
            json={"confirmed_item_ids": []},
        ).status_code == 403
        assert customer_client.post(
            f"/api/v1/sessions/{session_id}/step",
            json={"action": "next"},
        ).status_code == 403


def test_customer_cannot_manage_users(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as owner_client:
        owner_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "Test-owner-password-2026-is-long"},
        )
        owner_client.post(
            "/api/v1/auth/users",
            json={
                "email": "customer@example.test",
                "display_name": "عميل تجريبي",
                "password": "Customer-password-2026-is-strong",
                "role": "customer",
            },
        )

    with TestClient(app) as customer_client:
        customer_client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.test", "password": "Customer-password-2026-is-strong"},
        )
        customer_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Customer-password-2026-is-strong",
                "new_password": "Customer-new-password-2026-is-strong",
            },
        )
        assert customer_client.get("/api/v1/auth/users").status_code == 403


def test_eight_character_password_is_minimum_for_bootstrap_creation_and_rotation(monkeypatch):
    _configure_auth(monkeypatch)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "Ow8!Pass")
    get_settings.cache_clear()
    reset_caches()

    with TestClient(app) as owner_client, TestClient(app) as technician_client:
        owner_login = owner_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "Ow8!Pass"},
        )
        assert owner_login.status_code == 200

        too_short = owner_client.post(
            "/api/v1/auth/users",
            json={
                "email": "short.tech@example.test",
                "display_name": "فني قصير",
                "password": "Abc12!@",
                "role": "technician",
            },
        )
        assert too_short.status_code == 422

        created = owner_client.post(
            "/api/v1/auth/users",
            json={
                "email": "eight.tech@example.test",
                "display_name": "فني ثمانية",
                "password": "Abc123!@",
                "role": "technician",
            },
        )
        assert created.status_code == 201

        technician_login = technician_client.post(
            "/api/v1/auth/login",
            json={"email": "eight.tech@example.test", "password": "Abc123!@"},
        )
        assert technician_login.status_code == 200

        rotated = technician_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Abc123!@",
                "new_password": "N3wPass!",
            },
        )
        assert rotated.status_code == 200
