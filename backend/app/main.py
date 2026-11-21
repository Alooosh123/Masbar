from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import catalog, chat, health, sessions, tts, ws
from app.core.config import get_settings
from app.deps import get_assistant, get_kb
from app.safety.guard import SafetyViolation
from app.services.session import SessionNotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industrial-spatial-ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    kb = get_kb()
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
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(tts.router)
app.include_router(ws.router)
