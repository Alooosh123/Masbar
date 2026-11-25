from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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


class VerificationEvidence(BaseModel):
    """Human-reviewed, traceable evidence required before KB data can be marked verified."""

    source_document_id: str = Field(..., min_length=2)
    source_document_number: str = Field(..., min_length=2)
    source_revision: str = Field(..., min_length=1)
    source_sha256: str = Field(..., pattern=r"^[a-fA-F0-9]{64}$")
    source_page: int = Field(..., ge=1)
    equipment_model: str = Field(..., min_length=2)
    # Use an internal asset/nameplate reference; do not copy customer-sensitive serial data.
    nameplate_reference: str = Field(..., min_length=3)
    reviewed_by: str = Field(..., min_length=2)
    reviewed_at: datetime
    approved_by: str = Field(..., min_length=2)
    approved_at: datetime
    approval_reference: str = Field(..., min_length=3)
    reviewed_scopes: list[Literal["identity", "procedure", "torque", "safety"]] = Field(
        ..., min_length=1
    )

    @field_validator("reviewed_at", "approved_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verification timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_independent_review(self) -> "VerificationEvidence":
        if self.reviewed_by.strip().casefold() == self.approved_by.strip().casefold():
            raise ValueError("reviewer and approver must be different people")
        if self.approved_at < self.reviewed_at:
            raise ValueError("approval cannot predate the review")
        if len(self.reviewed_scopes) != len(set(self.reviewed_scopes)):
            raise ValueError("reviewed_scopes must not contain duplicates")
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
    verification_evidence: VerificationEvidence | None = None
    notes_ar: str | None = None

    @model_validator(mode="after")
    def validate_steps_and_evidence(self) -> "ComponentRecord":
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

        if self.verification_status == "verified":
            evidence = self.verification_evidence
            if evidence is None:
                raise ValueError(
                    f"verified component {self.part_number} requires verification_evidence"
                )
            if evidence.source_document_id != self.manual_doc_id:
                raise ValueError(
                    f"verification evidence for {self.part_number} does not match manual_doc_id"
                )
            if evidence.source_page != self.manual_page:
                raise ValueError(
                    f"verification evidence for {self.part_number} does not match manual_page"
                )
            if evidence.equipment_model not in self.equipment_models:
                raise ValueError(
                    f"verification evidence for {self.part_number} does not match equipment_models"
                )

            required_scopes = {"identity", "procedure"}
            if self.torque_nm is not None or any(step.requires_torque for step in self.steps):
                required_scopes.add("torque")
            if self.safety.loto_required or self.safety.warnings_ar:
                required_scopes.add("safety")
            missing_scopes = required_scopes.difference(evidence.reviewed_scopes)
            if missing_scopes:
                raise ValueError(
                    f"verified component {self.part_number} is missing reviewed scopes: "
                    f"{', '.join(sorted(missing_scopes))}"
                )
        return self


class EquipmentFile(BaseModel):
    schema_version: str = "1.0"
    equipment_family: str
    manufacturer: str
    data_status: Literal["sample", "verified"] = "sample"
    equipment_verification_evidence: VerificationEvidence | None = None
    disclaimer_ar: str = DEFAULT_DISCLAIMER_AR
    components: list[ComponentRecord] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_family_and_evidence(self) -> "EquipmentFile":
        evidence = self.equipment_verification_evidence
        if self.data_status == "verified":
            if evidence is None:
                raise ValueError("verified equipment requires equipment_verification_evidence")
            if evidence.equipment_model != self.equipment_family:
                raise ValueError("equipment verification evidence does not match equipment_family")
            if "identity" not in evidence.reviewed_scopes:
                raise ValueError("equipment verification evidence must include identity scope")

        for component in self.components:
            if self.equipment_family not in component.equipment_models:
                raise ValueError(
                    f"{component.part_number} does not list {self.equipment_family!r} "
                    "in its equipment_models"
                )
            if component.verification_status == "verified":
                if self.data_status != "verified" or evidence is None:
                    raise ValueError(
                        f"verified component {component.part_number} requires verified equipment evidence"
                    )
                component_evidence = component.verification_evidence
                if component_evidence is None:
                    raise ValueError(
                        f"verified component {component.part_number} requires component evidence"
                    )
                if component_evidence.equipment_model != self.equipment_family:
                    raise ValueError(
                        f"component evidence for {component.part_number} does not match equipment_family"
                    )
                if component_evidence.nameplate_reference != evidence.nameplate_reference:
                    raise ValueError(
                        f"component evidence for {component.part_number} uses a different nameplate reference"
                    )
        return self
