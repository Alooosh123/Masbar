from fastapi import APIRouter

from app.deps import get_assistant
from app.domain.api_models import (
    AskRequest,
    AssistantResponse,
    IdentifyRequest,
    LotoConfirmRequest,
    SessionAuditResponse,
    SessionCreateRequest,
    StepActionRequest,
)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", response_model=AssistantResponse, status_code=201)
@router.post("/", response_model=AssistantResponse, status_code=201, include_in_schema=False)
def create_session(req: SessionCreateRequest) -> AssistantResponse:
    return get_assistant().create_session(req)


@router.get("/{session_id}", response_model=AssistantResponse)
def get_session(session_id: str) -> AssistantResponse:
    return get_assistant().get_session(session_id)


@router.post("/{session_id}/identify", response_model=AssistantResponse)
async def identify_component(
    session_id: str, req: IdentifyRequest
) -> AssistantResponse:
    return await get_assistant().identify(session_id, req)


@router.post("/{session_id}/loto", response_model=AssistantResponse)
def confirm_loto(session_id: str, req: LotoConfirmRequest) -> AssistantResponse:
    return get_assistant().confirm_loto(session_id, req)


@router.post("/{session_id}/step", response_model=AssistantResponse)
def step_action(session_id: str, req: StepActionRequest) -> AssistantResponse:
    return get_assistant().step_action(session_id, req)


@router.post("/{session_id}/ask", response_model=AssistantResponse)
def ask(session_id: str, req: AskRequest) -> AssistantResponse:
    return get_assistant().ask(session_id, req)


@router.get("/{session_id}/audit", response_model=SessionAuditResponse)
def get_audit(session_id: str) -> SessionAuditResponse:
    return get_assistant().get_audit(session_id)
