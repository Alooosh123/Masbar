from __future__ import annotations

from app.domain.api_models import (
    SafetyChecklistItemState,
    SafetyLockoutProtocol,
    TorqueSpecification,
)
from app.domain.enums import SafetySeverity
from app.domain.kb import ComponentRecord, StepRecord
from app.knowledge.loader import KnowledgeBase

NM_TO_LBFT = 0.73756214927727


class SafetyViolation(Exception):
    """A deterministic safety rule rejected the requested operation."""

    def __init__(self, code: str, message_ar: str, status_code: int = 409):
        super().__init__(message_ar)
        self.code = code
        self.message_ar = message_ar
        self.status_code = status_code


class SafetyGuard:
    """
    Deterministic gate between raw knowledge and anything shown to the technician.

    Invariants enforced here:
      1. A part number must exist in the verified index.
      2. The part must belong to the selected equipment.
      3. Visual confidence must exceed the configured threshold.
      4. Torque values are only emitted from the knowledge base, never generated.
      5. LOTO is enforced server-side; the client cannot bypass it by skipping UI.
    """

    def __init__(self, kb: KnowledgeBase, min_visual_confidence: float = 0.85):
        self.kb = kb
        self.min_visual_confidence = min_visual_confidence

    # ------------------------------------------------------------------ lookup
    def require_component(self, part_number: str) -> ComponentRecord:
        if not part_number or not part_number.strip():
            raise SafetyViolation(
                "missing_part_number",
                "لم يتم تحديد رقم القطعة. وجّه الكاميرا نحو القطعة أو اخترها يدويًا.",
                status_code=422,
            )
        record = self.kb.get_component(part_number)
        if record is None:
            raise SafetyViolation(
                "unknown_part_number",
                f"رقم القطعة ({part_number}) غير موجود في السجلات المعتمدة. "
                "تحقق من الموديل أو امسح لوحة بيانات المعدة.",
                status_code=404,
            )
        return record

    def ensure_equipment(self, record: ComponentRecord, equipment_model: str) -> None:
        if equipment_model not in record.equipment_models:
            raise SafetyViolation(
                "equipment_mismatch",
                f"القطعة {record.part_number} لا تنتمي إلى المعدة المحددة ({equipment_model}). "
                "اختر المعدة الصحيحة قبل المتابعة.",
                status_code=409,
            )

    def confidence_allowed(self, confidence: float) -> bool:
        return confidence >= self.min_visual_confidence

    # ------------------------------------------------------------------ torque
    def build_torque(
        self, record: ComponentRecord, step: StepRecord
    ) -> TorqueSpecification | None:
        """Return torque only when the procedure step actually requires it."""
        if not step.requires_torque:
            return None

        value = step.torque_nm if step.torque_nm is not None else record.torque_nm
        if value is None:
            # Never invent a value. The assistant will explain that it is absent.
            return None

        sequence = step.tightening_sequence or record.tightening_sequence
        source_status = self.kb.data_status_for(record.part_number)
        verified_from_manual = (
            source_status == "verified" and record.verification_status == "verified"
        )
        return TorqueSpecification(
            value_nm=float(value),
            value_lbft=round(float(value) * NM_TO_LBFT, 1),
            tightening_sequence=sequence,
            verified_from_manual=verified_from_manual,
            source_document_id=record.manual_doc_id,
            source_page=record.manual_page,
            source_status=source_status,
        )

    # ------------------------------------------------------------------ safety
    def build_safety(
        self,
        record: ComponentRecord,
        confirmed_item_ids: set[str],
        acknowledged: bool,
    ) -> SafetyLockoutProtocol | None:
        requirement = record.safety
        if not requirement.loto_required and not requirement.warnings_ar:
            return None

        checklist = [
            SafetyChecklistItemState(
                id=item.id,
                label_ar=item.label_ar,
                confirmed=item.id in confirmed_item_ids,
            )
            for item in requirement.checklist
        ]

        blocked_reason = None
        if requirement.loto_required and not acknowledged:
            blocked_reason = (
                "بوابة السلامة مغلقة: يجب تأكيد جميع بنود العزل (LOTO) قبل عرض خطوات الفك."
            )

        return SafetyLockoutProtocol(
            severity=requirement.severity or SafetySeverity.WARNING,
            loto_required=requirement.loto_required,
            warnings_ar=list(requirement.warnings_ar),
            checklist=checklist,
            acknowledged_by_technician=acknowledged,
            blocked_reason_ar=blocked_reason,
        )

    def ensure_execution_allowed(self, record: ComponentRecord, acknowledged: bool) -> None:
        if record.safety.loto_required and not acknowledged:
            raise SafetyViolation(
                "loto_required",
                "لا يمكن عرض خطوات الفك قبل تأكيد إجراءات العزل (LOTO) على الشاشة.",
                status_code=409,
            )
