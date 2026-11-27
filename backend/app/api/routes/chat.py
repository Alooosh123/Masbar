import logging

from fastapi import APIRouter, HTTPException, Request

from app.deps import get_chat_service, get_conversation_store, get_store
from app.domain.api_models import ChatRequest, ChatResponse, ChatTurn
from app.services.session import SessionNotFound

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Handle chat and persist text history without exposing internal exceptions."""
    try:
        return await _handle_chat(req, request)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled chat request failure")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "chat_temporarily_unavailable",
                "message_ar": "تعذر إكمال المحادثة الآن بسبب عطل مؤقت في إحدى الخدمات. أعد المحاولة بعد قليل.",
            },
        ) from None


async def _handle_chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Handle chat and persist its text history in the authenticated user's scope."""
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return await get_chat_service().handle(req)

    message = (req.message or "").strip()
    has_image = bool(req.image_base64)
    if not message and not has_image:
        return await get_chat_service().handle(req)

    store = get_conversation_store()
    conversation_id = req.conversation_id
    if conversation_id:
        if store.get_owned(user.id, conversation_id) is None:
            raise HTTPException(status_code=404, detail={
                "code": "conversation_not_found",
                "message_ar": "المحادثة غير موجودة أو لا تملك صلاحية الوصول إليها.",
            })
    else:
        conversation = store.create(user.id)
        conversation_id = conversation["id"]

    history = store.history_for_model(user.id, conversation_id, limit=12)
    if history is None:
        raise HTTPException(status_code=404, detail={
            "code": "conversation_not_found",
            "message_ar": "المحادثة غير موجودة أو لا تملك صلاحية الوصول إليها.",
        })

    request_with_history = req.model_copy(
        update={
            "conversation_id": conversation_id,
            "history": [ChatTurn(**item) for item in history],
        }
    )
    response = await get_chat_service().handle(request_with_history)

    # Keep only a live, backend-validated session association. Conversation
    # history alone is never used to reconstruct equipment confirmation.
    linked_session_id = (
        response.session.session_id if response.session is not None else req.session_id
    )
    if linked_session_id:
        try:
            get_store().get(linked_session_id)
        except SessionNotFound:
            linked_session_id = None
    store.set_session_id(user.id, conversation_id, linked_session_id)

    stored_user_text = message or (
        "أرسل صورة لطلب تحديد قطعة." if req.mode == "identify" else "أرسل صورة للمحادثة."
    )
    store.append_message(
        user.id,
        conversation_id,
        "user",
        stored_user_text,
        has_image=has_image,
    )
    store.append_message(
        user.id,
        conversation_id,
        "assistant",
        response.message_ar,
        source=response.source,
    )
    response.conversation_id = conversation_id
    return response
