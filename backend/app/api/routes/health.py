from fastapi import APIRouter

from app.adapters.chat.factory import chat_is_configured
from app.adapters.tts.edge import tts_is_available
from app.deps import get_assistant, get_kb, get_manual_library, get_oem_registry
from app.domain.api_models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from app.core.config import get_settings

    settings = get_settings()
    kb = get_kb()
    return HealthResponse(
        status="online",
        app_version=settings.app_version,
        components=len(kb.components),
        equipment=len(kb.equipment),
        vision_provider=settings.vision_provider,
        vision_ready=(settings.vision_provider == "cohere" and bool(settings.cohere_api_key))\n        or (settings.vision_provider == "openai" and bool(settings.openai_api_key)),
        demo_mode=settings.demo_mode,
        chat_provider=settings.chat_provider if chat_is_configured(settings) else "disabled",
        chat_ready=chat_is_configured(settings),
        tts_provider=settings.tts_provider if tts_is_available(settings.tts_provider) else "disabled",
        tts_ready=tts_is_available(settings.tts_provider),
        manufacturers=get_oem_registry().count,
        manual_documents=len(get_manual_library().documents),
        manual_chunks=len(get_manual_library().chunks),
    )


@router.get("/")
def root() -> dict:
    return {
        "name": "Industrial Spatial AI Assistant",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
    }
