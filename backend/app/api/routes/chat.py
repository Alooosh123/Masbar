from fastapi import APIRouter

from app.deps import get_chat_service
from app.domain.api_models import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Single conversational entry point for text, camera images, and commands."""

    return await get_chat_service().handle(req)
