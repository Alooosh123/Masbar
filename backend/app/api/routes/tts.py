from fastapi import APIRouter, Depends, HTTPException, Response

from app.adapters.tts.edge import ARABIC_VOICES, EdgeTtsAdapter, TtsError
from app.deps import get_tts_adapter
from app.domain.api_models import TtsRequest

router = APIRouter(prefix="/api/v1", tags=["tts"])


@router.get("/tts/voices")
def list_arabic_voices() -> dict:
    return {
        "default": "ar-SA-ZariyahNeural",
        "voices": [
            {"id": voice_id, "label_ar": label}
            for voice_id, label in ARABIC_VOICES.items()
        ],
    }


@router.post("/tts")
async def synthesize_arabic(
    payload: TtsRequest,
    adapter: EdgeTtsAdapter = Depends(get_tts_adapter),
) -> Response:
    try:
        result = await adapter.synthesize(payload.text, payload.voice)
    except TtsError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "tts_unavailable", "message_ar": str(exc)},
        ) from exc

    return Response(
        content=result.audio,
        media_type=result.mime_type,
        headers={
            "Cache-Control": "no-store",
            "X-TTS-Voice": result.voice,
            "X-TTS-Language": "ar",
        },
    )
