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

    def procedure_is_verified(self, record: ComponentRecord) -> bool:
        """Require a model and component evidence chain before enabling maintenance."""
        if self.kb.data_status_for(record.part_number) != "verified":
            return False
        equipment_evidence = None
        for model in record.equipment_models:
            equipment_file = self.kb.equipment_files.get(model)
            if equipment_file is not None:
                equipment_evidence = equipment_file.equipment_verification_evidence
                if equipment_file.data_status == "verified":
                    break
        evidence = record.verification_evidence
        required_scopes = {"identity", "procedure", "safety"}
        return bool(
            record.verification_status == "verified"
            and evidence is not None
            and equipment_evidence is not None
            and evidence.source_document_id == record.manual_doc_id
            and evidence.source_page == record.manual_page
            and evidence.equipment_model in record.equipment_models
            and required_scopes.issubset(set(evidence.reviewed_scopes))
            and equipment_evidence.equipment_model == evidence.equipment_model
            and equipment_evidence.nameplate_reference == evidence.nameplate_reference
            and "identity" in equipment_evidence.reviewed_scopes
        )

    def ensure_procedure_allowed(
        self, record: ComponentRecord, acknowledged: bool
    ) -> None:
        """Fail closed unless isolation and independently-reviewed OEM evidence exist."""
        self.ensure_execution_allowed(record, acknowledged)
        if not self.procedure_is_verified(record):
            raise SafetyViolation(
                "procedure_not_verified",
                "تم تحديد القطعة، لكن لا توجد لها تعليمات صيانة وسلامة معتمدة "
                "ومطابقة للمعدة في قاعدة المعرفة. لن أعرض خطوات الفك أو التركيب "
                "أو عزم الشد. أرفق كتيب الشركة المطابق للطراز واطلب مراجعته واعتماده.",
                status_code=409,
            )

    # ------------------------------------------------------------------ torque
    def build_torque(
        self, record: ComponentRecord, step: StepRecord
    ) -> TorqueSpecification | None:
        """Return torque only when the procedure step actually requires it."""
        if not step.requires_torque:
            return None

        evidence = record.verification_evidence
        if (
            not self.procedure_is_verified(record)
            or evidence is None
            or "torque" not in evidence.reviewed_scopes
        ):
            # Sample/demo values are never surfaced as operational torque.
            return None

        value = step.torque_nm if step.torque_nm is not None else record.torque_nm
        if value is None:
            return None

        sequence = step.tightening_sequence or record.tightening_sequence
        return TorqueSpecification(
            value_nm=float(value),
            value_lbft=round(float(value) * NM_TO_LBFT, 1),
            tightening_sequence=sequence,
            verified_from_manual=True,
            source_document_id=record.manual_doc_id,
            source_page=record.manual_page,
            source_status="verified",
        )

    # ------------------------------------------------------------------ safety
    def build_safety(
        self,
        record: ComponentRecord,
        confirmed_item_ids: set[str],
        acknowledged: bool,
    ) -> SafetyLockoutProtocol | None:
        if not self.procedure_is_verified(record):
            return SafetyLockoutProtocol(
                severity=SafetySeverity.CRITICAL,
                loto_required=True,
                warnings_ar=[
                    "لا توجد معلومات عزل وسلامة معتمدة ومطابقة لهذا الطراز. "
                    "لا تبدأ الفك أو التشغيل أو الصيانة اعتمادًا على بيانات العرض."
                ],
                checklist=[],
                acknowledged_by_technician=False,
                blocked_reason_ar=(
                    "تم إيقاف الإجراء لأن تعليمات السلامة لم تجتز مراجعة المصدر والمعدة."
                ),
                source_status="unverified",
            )

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
            source_status="verified",
        )

    def ensure_execution_allowed(self, record: ComponentRecord, acknowledged: bool) -> None:
        if record.safety.loto_required and not acknowledged:
            raise SafetyViolation(
                "loto_required",
                "لا يمكن عرض خطوات الفك قبل تأكيد إجراءات العزل (LOTO) على الشاشة.",
                status_code=409,
            )
