from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import reset_caches
from app.main import app
from app.security.auth import AuthStore, issue_token, user_from_token


def test_password_storage_and_expiring_signed_access_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "unit-test-secret-with-more-than-thirty-two-characters")
    get_settings.cache_clear()

    store = AuthStore(tmp_path / "auth.sqlite3")
    owner = store.create_first_owner(
        email="owner@example.test",
        full_name="Owner",
        password="a-long-password-for-tests",
        setup_token="one-time-bootstrap-token",
        expected_setup_token="one-time-bootstrap-token",
    )

    assert store.count() == 1
    assert store.authenticate("OWNER@example.test", "a-long-password-for-tests")["role"] == "owner"
    assert store.authenticate("owner@example.test", "wrong-password") is None

    token = issue_token(owner)
    assert user_from_token(token)["id"] == owner["id"]
    assert "a-long-password-for-tests" not in token
    get_settings.cache_clear()


def test_api_requires_auth_and_enforces_technical_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "unit-test-secret-with-more-than-thirty-two-characters")
    monkeypatch.setenv("AUTH_SETUP_TOKEN", "one-time-bootstrap-token-for-tests")
    get_settings.cache_clear()
    reset_caches()

    try:
        with TestClient(app) as client:
            status_response = client.get("/api/v1/auth/status")
            assert status_response.status_code == 200
            assert status_response.json()["initial_setup_required"] is True

            initialized = client.post(
                "/api/v1/auth/initialize",
                json={
                    "setup_token": "one-time-bootstrap-token-for-tests",
                    "email": "owner@example.test",
                    "full_name": "Owner",
                    "password": "owner-password-long-enough",
                },
            )
            assert initialized.status_code == 201
            owner_token = initialized.json()["access_token"]

            assert client.get("/api/v1/equipment").status_code == 401
            headers = {"Authorization": f"Bearer {owner_token}"}
            assert client.get("/api/v1/equipment", headers=headers).status_code == 200

            viewer_created = client.post(
                "/api/v1/auth/users",
                headers=headers,
                json={
                    "email": "viewer@example.test",
                    "full_name": "Viewer",
                    "password": "viewer-password-long-enough",
                    "role": "viewer",
                },
            )
            assert viewer_created.status_code == 201
            viewer_login = client.post(
                "/api/v1/auth/login",
                json={
                    "email": "viewer@example.test",
                    "password": "viewer-password-long-enough",
                },
            )
            viewer_token = viewer_login.json()["access_token"]
            viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

            assert client.post(
                "/api/v1/sessions",
                headers=viewer_headers,
                json={"equipment_model": "Caterpillar C15 ACERT"},
            ).status_code == 403
            assert client.post(
                "/api/v1/sessions",
                headers=headers,
                json={"equipment_model": "Caterpillar C15 ACERT"},
            ).status_code == 201
            assert client.post(
                "/api/v1/auth/initialize",
                json={
                    "setup_token": "one-time-bootstrap-token-for-tests",
                    "email": "second@example.test",
                    "full_name": "Second",
                    "password": "another-password-long-enough",
                },
            ).status_code == 409
    finally:
        reset_caches()
        get_settings.cache_clear()
