from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import CueType, SafetySeverity

DEFAULT_DISCLAIMER_AR = (
    "هذه البيانات نموذجية لأغراض العرض والاختبار فقط، وليست مقتطفة من كتيب صيانة رسمي. "
    "لا يجوز الاعتماد عليها في صيانة معدات حقيقية. ارجع دائمًا إلى كتيب الشركة المصنّعة وإجراءات السلامة المعتمدة."
)


class ChecklistItem(BaseModel):
    id: str = Field(..., min_length=2)
    label_ar: str = Field(..., min_length=3)


class SafetyRequirement(BaseModel):
    loto_required: bool = False
    severity: SafetySeverity = SafetySeverity.INFO
    warnings_ar: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_loto(self) -> "SafetyRequirement":
        if self.loto_required and not self.checklist:
            raise ValueError("LOTO is required but no safety checklist items were provided")
        if self.severity == SafetySeverity.CRITICAL and not self.warnings_ar:
            raise ValueError("CRITICAL severity requires at least one Arabic warning")
        return self


class CueSpec(BaseModel):
    cue_type: CueType = CueType.HIGHLIGHT_MESH
    direction: str | None = None
    color_hex: str = "#F59E0B"


class RelatedPart(BaseModel):
    part_number: str
    name_ar: str
    name_en: str


class StepRecord(BaseModel):
    step_number: int = Field(..., ge=1)
    instruction_ar: str = Field(..., min_length=5)
    tool_required_ar: str = Field(..., min_length=2)
    requires_torque: bool = False
    torque_nm: float | None = Field(default=None, gt=0)
    tightening_sequence: str | None = None
    warning_ar: str | None = None
    verification_ar: str | None = None
    cue: CueSpec = Field(default_factory=CueSpec)


class ComponentRecord(BaseModel):
    part_number: str = Field(..., min_length=2)
    english_name: str
    arabic_name: str
    equipment_models: list[str] = Field(..., min_length=1)
    manual_doc_id: str
    manual_page: int = Field(..., ge=1)
    section_title: str
    torque_nm: float | None = Field(default=None, gt=0)
    tightening_sequence: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    symptoms_ar: list[str] = Field(default_factory=list)
    related_parts: list[RelatedPart] = Field(default_factory=list)
    safety: SafetyRequirement = Field(default_factory=SafetyRequirement)
    steps: list[StepRecord] = Field(..., min_length=1)
    verification_status: Literal["sample", "verified"] = "sample"
    notes_ar: str | None = None

    @model_validator(mode="after")
    def validate_steps(self) -> "ComponentRecord":
        expected = list(range(1, len(self.steps) + 1))
        actual = [step.step_number for step in self.steps]
        if actual != expected:
            raise ValueError(
                f"steps for {self.part_number} must be sequential starting at 1, got {actual}"
            )
        for step in self.steps:
            if (
                step.requires_torque
                and step.torque_nm is None
                and self.torque_nm is None
            ):
                raise ValueError(
                    f"step {step.step_number} of {self.part_number} requires torque "
                    "but no torque value exists at step or component level"
                )
        return self


class EquipmentFile(BaseModel):
    schema_version: str = "1.0"
    equipment_family: str
    manufacturer: str
    data_status: Literal["sample", "verified"] = "sample"
    disclaimer_ar: str = DEFAULT_DISCLAIMER_AR
    components: list[ComponentRecord] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_family(self) -> "EquipmentFile":
        for component in self.components:
            if self.equipment_family not in component.equipment_models:
                raise ValueError(
                    f"{component.part_number} does not list {self.equipment_family!r} "
                    "in its equipment_models"
                )
        return self
