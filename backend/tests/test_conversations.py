from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.deps import get_assistant, reset_caches
from app.domain.api_models import ChatResponse, SessionCreateRequest
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


class _ChatStub:
    def __init__(self):
        self.requests = []

    async def handle(self, req):
        self.requests.append(req)
        return ChatResponse(
            message_ar=f"رد محفوظ رقم {len(self.requests)}",
            source="general",
            session=getattr(self, "session", None),
        )


def _login(client, email, password):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_customer_conversations_persist_and_are_isolated_by_account(monkeypatch):
    _configure_auth(monkeypatch)
    chat_stub = _ChatStub()
    monkeypatch.setattr("app.api.routes.chat.get_chat_service", lambda: chat_stub)

    with TestClient(app) as owner:
        assert _login(owner, "owner@example.test", "Test-owner-password-2026-is-long").status_code == 200
        first = owner.post(
            "/api/v1/auth/users/customers",
            json={"email": "first.customer@example.test", "display_name": "العميل الأول"},
        )
        second = owner.post(
            "/api/v1/auth/users/customers",
            json={"email": "second.customer@example.test", "display_name": "العميل الثاني"},
        )
        assert first.status_code == 201
        assert second.status_code == 201

    # The session is created by the backend identification workflow and
    # attached to the authenticated conversation response.
    chat_stub.session = get_assistant().create_session(
        SessionCreateRequest(equipment_model="Siemens S7-1200 Control Panel")
    )

    with TestClient(app) as customer_one, TestClient(app) as customer_two:
        password_one = first.json()["temporary_password"]
        password_two = second.json()["temporary_password"]
        assert _login(customer_one, "first.customer@example.test", password_one).status_code == 200
        assert _login(customer_two, "second.customer@example.test", password_two).status_code == 200
        assert customer_one.post(
            "/api/v1/auth/change-password",
            json={"current_password": password_one, "new_password": "First!Pass8"},
        ).status_code == 200
        assert customer_two.post(
            "/api/v1/auth/change-password",
            json={"current_password": password_two, "new_password": "Second!Pass8"},
        ).status_code == 200

        first_turn = customer_one.post("/api/v1/chat", json={"message": "أحتاج فحص المضخة"})
        assert first_turn.status_code == 200
        conversation_id = first_turn.json()["conversation_id"]
        assert conversation_id.startswith("conv_")

        second_turn = customer_one.post(
            "/api/v1/chat",
            json={
                "message": "تابع من فضلك",
                "conversation_id": conversation_id,
                # The server must ignore caller-supplied history and load its own record.
                "history": [{"role": "user", "content": "سياق مزيف من المتصفح"}],
            },
        )
        assert second_turn.status_code == 200

        assert len(chat_stub.requests) == 2
        assert [(turn.role, turn.content) for turn in chat_stub.requests[1].history] == [
            ("user", "أحتاج فحص المضخة"),
            ("assistant", "رد محفوظ رقم 1"),
        ]

        listed = customer_one.get("/api/v1/conversations")
        assert listed.status_code == 200
        assert len(listed.json()["conversations"]) == 1
        summary = listed.json()["conversations"][0]
        assert summary["id"] == conversation_id
        assert summary["title"] == "أحتاج فحص المضخة"
        assert summary["message_count"] == 4
        assert summary["session_id"] == chat_stub.session.session_id

        opened = customer_one.get(f"/api/v1/conversations/{conversation_id}")
        assert opened.status_code == 200
        assert [item["role"] for item in opened.json()["messages"]] == [
            "user", "assistant", "user", "assistant"
        ]
        assert opened.json()["conversation"]["session_id"] == chat_stub.session.session_id

        # A different customer cannot list, read, continue, or delete this record.
        assert customer_two.get("/api/v1/conversations").json()["conversations"] == []
        assert customer_two.get(f"/api/v1/conversations/{conversation_id}").status_code == 404
        assert customer_two.post(
            "/api/v1/chat",
            json={"message": "محاولة وصول", "conversation_id": conversation_id},
        ).status_code == 404
        assert customer_two.delete(f"/api/v1/conversations/{conversation_id}").status_code == 404

        deleted = customer_one.delete(f"/api/v1/conversations/{conversation_id}")
        assert deleted.status_code == 200
        assert customer_one.get("/api/v1/conversations").json()["conversations"] == []


def test_conversation_endpoints_require_authentication(monkeypatch):
    _configure_auth(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/v1/conversations").status_code == 401
        assert client.get("/api/v1/conversations/conv_unknown").status_code == 401
