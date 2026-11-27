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


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_owner_can_create_list_update_and_disable_only_customer_accounts(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as owner, TestClient(app) as customer:
        assert _login(owner, "owner@example.test", "Test-owner-password-2026-is-long").status_code == 200

        created = owner.post(
            "/api/v1/auth/users/customers",
            json={"email": "new.customer@example.test", "display_name": "عميل جديد"},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["user"]["role"] == "customer"
        assert payload["user"]["must_change_password"] is True
        temporary_password = payload["temporary_password"]
        assert len(temporary_password) >= 30

        listed = owner.get("/api/v1/auth/users/customers")
        assert listed.status_code == 200
        assert [item["email"] for item in listed.json()["customers"]] == ["new.customer@example.test"]

        assert _login(customer, "new.customer@example.test", temporary_password).status_code == 200
        assert customer.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        ).json()["detail"]["code"] == "password_change_required"

        changed = customer.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": temporary_password,
                "new_password": "Customer-own-password-2026-is-safe",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["user"]["must_change_password"] is False
        rejected_session = customer.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert rejected_session.status_code == 409
        assert rejected_session.json()["detail"]["code"] == "image_identification_required"

        customer_id = payload["user"]["id"]
        updated = owner.patch(
            f"/api/v1/auth/users/{customer_id}",
            json={"display_name": "عميل محدث", "email": "updated.customer@example.test"},
        )
        assert updated.status_code == 200
        assert updated.json()["user"]["display_name"] == "عميل محدث"
        assert updated.json()["user"]["email"] == "updated.customer@example.test"

        deactivated = owner.post(
            f"/api/v1/auth/users/{customer_id}/activation",
            json={"is_active": False},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["user"]["is_active"] is False
        assert customer.get("/api/v1/auth/me").json()["authenticated"] is False
        assert _login(customer, "updated.customer@example.test", "Customer-own-password-2026-is-safe").status_code == 401

        activated = owner.post(
            f"/api/v1/auth/users/{customer_id}/activation",
            json={"is_active": True},
        )
        assert activated.status_code == 200
        assert activated.json()["user"]["is_active"] is True


def test_customer_password_reset_returns_one_time_password_and_revokes_sessions(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as owner, TestClient(app) as customer:
        assert _login(owner, "owner@example.test", "Test-owner-password-2026-is-long").status_code == 200
        created = owner.post(
            "/api/v1/auth/users/customers",
            json={"email": "reset.customer@example.test", "display_name": "عميل الاستعادة"},
        )
        customer_id = created.json()["user"]["id"]
        first_password = created.json()["temporary_password"]

        assert _login(customer, "reset.customer@example.test", first_password).status_code == 200
        assert customer.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": first_password,
                "new_password": "Customer-first-password-2026-safe",
            },
        ).status_code == 200

        reset = owner.post(f"/api/v1/auth/users/{customer_id}/reset-password")
        assert reset.status_code == 200
        reset_data = reset.json()
        second_password = reset_data["temporary_password"]
        assert second_password != first_password
        assert reset_data["must_change_password"] is True
        assert customer.get("/api/v1/auth/me").json()["authenticated"] is False
        assert _login(customer, "reset.customer@example.test", "Customer-first-password-2026-safe").status_code == 401

        assert _login(customer, "reset.customer@example.test", second_password).status_code == 200
        me = customer.get("/api/v1/auth/me").json()
        assert me["user"]["must_change_password"] is True
        catalog_blocked = customer.get("/api/v1/equipment")
        assert catalog_blocked.status_code == 403
        assert catalog_blocked.json()["detail"]["code"] == "password_change_required"
        blocked = customer.post(
            "/api/v1/sessions",
            json={"equipment_model": "Caterpillar C15 ACERT"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "password_change_required"

        completed = customer.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": second_password,
                "new_password": "Customer-second-password-2026-safe",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["user"]["must_change_password"] is False


def test_customer_cannot_access_customer_management_endpoints(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as owner, TestClient(app) as customer:
        assert _login(owner, "owner@example.test", "Test-owner-password-2026-is-long").status_code == 200
        created = owner.post(
            "/api/v1/auth/users/customers",
            json={"email": "restricted.customer@example.test", "display_name": "عميل محدود"},
        )
        assert created.status_code == 201
        temporary_password = created.json()["temporary_password"]

        assert _login(customer, "restricted.customer@example.test", temporary_password).status_code == 200
        # Password rotation is the only protected action allowed before activation.
        assert customer.get("/api/v1/auth/users/customers").status_code == 403
        assert customer.post("/api/v1/auth/users/unknown/reset-password").status_code == 403
        assert customer.patch(
            f"/api/v1/auth/users/{created.json()['user']['id']}",
            json={"display_name": "تغيير غير مصرح"},
        ).status_code == 403
