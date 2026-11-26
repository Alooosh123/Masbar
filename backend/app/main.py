from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, catalog, chat, health, manuals, sessions, tts, ws
from app.ops.sqlite_backup import create_sqlite_backup, prune_sqlite_backups
from app.core.config import get_settings
from app.deps import get_assistant, get_auth_store, get_kb
from app.security.auth import AUTH_COOKIE_NAME, get_current_user
from app.safety.guard import SafetyViolation
from app.services.session import SessionNotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industrial-spatial-ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    kb = get_kb()
    if settings.auth_required:
        get_auth_store()
    get_assistant()  # fail fast on bad vision configuration
    logger.info(
        "Knowledge base loaded: %s components across %s equipment models",
        len(kb.components),
        len(kb.equipment),
    )
    logger.info(
        "Vision provider=%s | demo_mode=%s | min_confidence=%.2f",
        settings.vision_provider,
        settings.demo_mode,
        settings.min_visual_confidence,
    )
    if settings.sqlite_backup_on_startup:
        backup_dir = settings.sqlite_backup_dir or (settings.session_db_path.parent / "backups")
        try:
            result = await asyncio.to_thread(
                create_sqlite_backup,
                settings.session_db_path,
                backup_dir,
            )
            removed = await asyncio.to_thread(
                prune_sqlite_backups,
                backup_dir,
                settings.sqlite_backup_retention_days,
            )
            logger.info(
                "SQLite startup backup verified: file=%s size_bytes=%s sha256=%s pruned=%s",
                Path(result.backup_path).name,
                result.size_bytes,
                result.sha256,
                len(removed),
            )
        except Exception:
            logger.exception("SQLite startup backup failed; original database remains in place")
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Real-time multimodal spatial assistant for industrial maintenance. "
        "Deterministic safety guardrails with Arabic dialect support."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.auth_required,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_api_auth(request: Request, call_next):
    runtime_settings = get_settings()
    path = request.url.path

    if request.method not in {"GET", "HEAD", "OPTIONS"} and runtime_settings.auth_required:
        origin = request.headers.get("origin")
        if origin:
            from app.security.auth import origin_is_trusted
            if not origin_is_trusted(origin, runtime_settings.cors_origin_list):
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"code": "untrusted_origin", "message_ar": "مصدر الطلب غير موثوق."}},
                )

    public_auth_paths = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    }
    if path in public_auth_paths or path == "/health" or request.method == "OPTIONS":
        return await call_next(request)

    has_auth_token = bool(
        request.cookies.get(AUTH_COOKIE_NAME)
        or request.headers.get("authorization", "").lower().startswith("bearer ")
    )
    if (
        runtime_settings.auth_required
        and has_auth_token
        and path != "/api/v1/auth/change-password"
    ):
        pending_user = get_current_user(request, required=False)
        if pending_user is not None and pending_user.must_change_password:
            return JSONResponse(
                status_code=403,
                content={"detail": {"code": "password_change_required", "message_ar": "يجب تغيير كلمة المرور المؤقتة قبل استخدام التطبيق."}},
            )

    is_user_admin = path.startswith("/api/v1/auth/users")
    is_change_password = path == "/api/v1/auth/change-password"
    protected_prefixes = (
        "/api/v1/chat",
        "/api/v1/sessions",
        "/api/v1/manuals",
        "/api/v1/tts",
    )
    is_protected = is_user_admin or is_change_password or path.startswith(protected_prefixes)

    if not is_protected:
        return await call_next(request)
    if not runtime_settings.auth_required:
        if is_user_admin or is_change_password:
            return JSONResponse(
                status_code=503,
                content={"detail": {"code": "auth_disabled", "message_ar": "فعّل المصادقة أولاً لإدارة المستخدمين."}},
            )
        return await call_next(request)

    try:
        user = get_current_user(request)
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    if user is None:
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": "authentication_required", "message_ar": "سجّل الدخول للمتابعة."}},
        )

    if is_user_admin and user.role not in {"owner", "admin"}:
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "insufficient_role", "message_ar": "إدارة الحسابات تتطلب صلاحية المالك أو المدير."}},
        )

    if user.must_change_password and path not in {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/change-password",
    }:
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "password_change_required", "message_ar": "يجب تغيير كلمة المرور المؤقتة قبل استخدام التطبيق."}},
        )

    if user.role == "customer":
        session_path = path.startswith("/api/v1/sessions")
        session_action = path.rsplit("/", 1)[-1] if session_path else ""
        is_session_create = path.rstrip("/") == "/api/v1/sessions" and request.method == "POST"
        is_customer_session_action = (
            session_path
            and request.method == "POST"
            and session_action in {"identify", "ask"}
        )
        is_customer_chat = path == "/api/v1/chat" and request.method == "POST"
        is_customer_tts = path.startswith("/api/v1/tts") and request.method == "POST"
        is_customer_password_change = path == "/api/v1/auth/change-password" and request.method == "POST"
        is_customer_read = session_path and request.method == "GET"
        if (
            is_customer_chat
            or is_customer_tts
            or is_customer_password_change
            or is_session_create
            or is_customer_session_action
            or is_customer_read
        ):
            request.state.auth_user = user
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "customer_action_restricted",
                    "message_ar": "حساب العميل يتيح المحادثة وتحليل القطع وعرض الجلسات. اعتماد العزل وتشغيل خطوات الصيانة متاح للفنيين المعتمدين فقط.",
                }
            },
        )

    if (
        (path.startswith("/api/v1/chat") or (path.startswith("/api/v1/sessions") and request.method != "GET"))
        and user.role not in {"owner", "admin", "technician"}
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "read_only_role", "message_ar": "حساب المشاهدة لا يملك صلاحية تعديل جلسات الصيانة."}},
        )

    request.state.auth_user = user
    return await call_next(request)


@app.exception_handler(SafetyViolation)
async def safety_violation_handler(request: Request, exc: SafetyViolation) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message_ar": exc.message_ar}},
    )


@app.exception_handler(SessionNotFound)
async def session_not_found_handler(request: Request, exc: SessionNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": {
                "code": "session_not_found",
                "message_ar": "الجلسة غير موجودة أو انتهت صلاحيتها. ابدأ جلسة جديدة.",
            }
        },
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(manuals.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(tts.router)
app.include_router(ws.router)
