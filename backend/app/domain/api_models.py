from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import (
    CueType,
    IdentificationSource,
    Intent,
    SafetySeverity,
    SessionState,
)


class EquipmentSummary(BaseModel):
    equipment_family: str
    manufacturer: str
    component_count: int
    data_status: str


class ComponentSummary(BaseModel):
    part_number: str
    english_name: str
    arabic_name: str
    equipment_models: list[str]
    verification_status: str


class SessionCreateRequest(BaseModel):
    equipment_model: str = Field(..., min_length=2)


class IdentifyRequest(BaseModel):
    part_number: str | None = None
    transcript: str | None = None
    image_base64: str | None = None
    visual_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    bounding_box: tuple[float, float, float, float] | None = None


class LotoConfirmRequest(BaseModel):
    confirmed_item_ids: list[str] = Field(default_factory=list)
    technician_note: str | None = None


class StepActionRequest(BaseModel):
    action: Literal["next", "prev", "repeat", "goto"] = "next"
    step_index: int | None = Field(default=None, ge=1)


class AskRequest(BaseModel):
    transcript: str = Field(..., min_length=1)


class TorqueSpecification(BaseModel):
    value_nm: float
    value_lbft: float
    tightening_sequence: str | None = None
    verified_from_manual: bool = True
    source_document_id: str
    source_page: int
    source_status: str = "sample"


class IdentifiedComponent(BaseModel):
    part_number: str
    english_name: str
    arabic_name: str
    confidence_score: float
    bounding_box_2d: tuple[float, float, float, float]
    anchor_3d_offset: dict[str, float] = Field(
        default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0}
    )
    identification_source: IdentificationSource
    verification_status: str = "sample"


class ARVisualCue(BaseModel):
    cue_type: CueType
    direction: str | None = None
    color_hex: str = "#F59E0B"
    label_ar: str | None = None


class MaintenanceStep(BaseModel):
    step_number: int
    total_steps: int
    instruction_ar: str
    tool_required_ar: str
    torque_spec: TorqueSpecification | None = None
    warning_ar: str | None = None
    verification_ar: str | None = None
    ar_visual_cue: ARVisualCue


class ManualReference(BaseModel):
    document_id: str
    page_number: int
    section_title: str
    verification_status: str


class SafetyChecklistItemState(BaseModel):
    id: str
    label_ar: str
    confirmed: bool = False


class SafetyLockoutProtocol(BaseModel):
    severity: SafetySeverity
    loto_required: bool
    warnings_ar: list[str]
    checklist: list[SafetyChecklistItemState] = Field(default_factory=list)
    acknowledged_by_technician: bool = False
    blocked_reason_ar: str | None = None


class RetrievalCandidate(BaseModel):
    part_number: str
    arabic_name: str
    english_name: str
    score: float


class AuditEntry(BaseModel):
    id: str
    timestamp: datetime
    event: str
    detail_ar: str


class AssistantResponse(BaseModel):
    session_id: str
    identification_id: str | None = None
    state: SessionState
    equipment_model: str
    requires_closer_inspection: bool = False
    inspection_prompt_ar: str | None = None
    identified_component: IdentifiedComponent | None = None
    safety_lockout: SafetyLockoutProtocol | None = None
    current_step: MaintenanceStep | None = None
    manual_reference: ManualReference | None = None
    assistant_message_ar: str = ""
    next_actions_ar: list[str] = Field(default_factory=list)
    data_disclaimer_ar: str = ""
    retrieval_candidates: list[RetrievalCandidate] = Field(default_factory=list)
    last_intent: Intent | None = None


class SessionAuditResponse(BaseModel):
    session_id: str
    state: SessionState
    entries: list[AuditEntry]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    image_base64: str | None = None
    session_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)
    mode: Literal["auto", "describe", "identify"] = "auto"


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    voice: str | None = None


class ChatResponse(BaseModel):
    message_ar: str
    source: Literal["assistant", "general", "vision", "system"]
    action: Literal[
        "open_camera",
        "close_camera",
        "start_listening",
        "stop_listening",
    ] | None = None
    session: AssistantResponse | None = None
    equipment: list[EquipmentSummary] = Field(default_factory=list)
    components: list[ComponentSummary] = Field(default_factory=list)
    quick_replies: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app_version: str
    components: int
    equipment: int
    vision_provider: str
    demo_mode: bool
    chat_provider: str = "disabled"
    chat_ready: bool = False
    tts_provider: str = "disabled"
    tts_ready: bool = False
    manufacturers: int = 0


class ManufacturerSummary(BaseModel):
    id: str
    name_ar: str
    name_en: str
    country_ar: str
    official_url: str
    data_access: str
    models_count: int
    categories_ar: list[str] = Field(default_factory=list)
    notes_ar: str = ""
