from fastapi import APIRouter, HTTPException, Request

from app.deps import get_conversation_store

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _user_id(request: Request) -> str:
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail={
            "code": "authentication_required",
            "message_ar": "سجّل الدخول لعرض سجل المحادثات.",
        })
    return user.id


@router.get("")
def list_conversations(request: Request) -> dict:
    """Return only conversations owned by the authenticated user."""
    return {"conversations": get_conversation_store().list_for_user(_user_id(request))}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict:
    user_id = _user_id(request)
    store = get_conversation_store()
    conversation = store.get_owned(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail={
            "code": "conversation_not_found",
            "message_ar": "المحادثة غير موجودة أو لا تملك صلاحية الوصول إليها.",
        })
    messages = store.messages_for_user(user_id, conversation_id)
    return {"conversation": conversation, "messages": messages or []}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request) -> dict:
    user_id = _user_id(request)
    if not get_conversation_store().delete(user_id, conversation_id):
        raise HTTPException(status_code=404, detail={
            "code": "conversation_not_found",
            "message_ar": "المحادثة غير موجودة أو لا تملك صلاحية حذفها.",
        })
    return {"deleted": True, "conversation_id": conversation_id}
