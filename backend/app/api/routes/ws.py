from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.deps import get_assistant
from app.services.session import SessionNotFound
from app.core.config import get_settings
from app.security.auth import websocket_user

router = APIRouter(tags=["stream"])


@router.websocket("/api/v1/sessions/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    """
    Lightweight real-time channel: sends the current session snapshot on connect,
    then echoes pings. Mutations happen over HTTP and the client refetches.

    This keeps Milestone 1 dependency-free; a later iteration can push deltas
    from a shared event bus without changing the client contract.
    """
    settings = get_settings()
    if settings.auth_required and websocket_user(websocket) is None:
        await websocket.close(code=4401)
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
