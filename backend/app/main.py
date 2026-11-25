from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, catalog, chat, health, manuals, sessions, tts, ws
from app.core.config import get_settings
from app.deps import get_assistant, get_kb
from app.safety.guard import SafetyViolation
from app.security.auth import get_current_user, require_roles
from app.services.session import SessionNotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industrial-spatial-ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    kb = get_kb()
    get_assistant()
    logger.info(
        "Knowledge base loaded: %s components across %s equipment models",
        len(kb.components),
        len(kb.equipment),
    )
    logger.info(
        "Vision provider=%s | chat_provider=%s | auth_enabled=%s | demo_mode=%s",
        settings.vision_provider,
        settings.chat_provider,
        settings.auth_enabled,
        settings.demo_mode,
    )
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
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


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
authenticated = [Depends(get_current_user)]
technical = [Depends(require_roles("owner", "manager", "engineer", "technician"))]
app.include_router(catalog.router, dependencies=authenticated)
app.include_router(manuals.router, dependencies=authenticated)
app.include_router(sessions.router, dependencies=authenticated)
app.include_router(chat.router, dependencies=technical)
app.include_router(tts.router, dependencies=authenticated)
app.include_router(ws.router)
