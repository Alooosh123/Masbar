from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.deps import get_assistant
from app.security.auth import user_from_token
from app.services.session import SessionNotFound

router = APIRouter(tags=["stream"])


@router.websocket("/api/v1/sessions/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    """Read-only session events. Authenticated with a short-lived bearer token."""
    settings = get_settings()
    if settings.auth_enabled:
        token = websocket.query_params.get("access_token")
        if not token or user_from_token(token) is None:
            await websocket.close(code=4401, reason="authentication_required")
            return

    await websocket.accept()
    try:
        response = get_assistant().get_session(session_id)
    except SessionNotFound:
        await websocket.send_json({"type": "error", "code": "session_not_found"})
        await websocket.close(code=4404)
        return

    await websocket.send_json(
        {"type": "session_state", "payload": response.model_dump(mode="json")}
    )

    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        return
