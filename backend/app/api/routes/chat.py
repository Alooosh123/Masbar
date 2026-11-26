from fastapi import APIRouter, HTTPException, Request

from app.deps import get_chat_service, get_conversation_store
from app.domain.api_models import ChatRequest, ChatResponse, ChatTurn

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
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

    # Server-side history is authoritative; the browser cannot inject another
    # user's transcript into this conversation's model context.
    request_with_history = req.model_copy(
        update={
            "conversation_id": conversation_id,
            "history": [ChatTurn(**item) for item in history],
        }
    )
    response = await get_chat_service().handle(request_with_history)

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
