from __future__ import annotations

import secrets

from app.adapters.vision.base import VisionResult
from app.core.config import Settings
from app.domain.api_models import (
    ARVisualCue,
    AskRequest,
    AssistantResponse,
    ComponentSummary,
    EquipmentSummary,
    IdentifiedComponent,
    IdentifyRequest,
    LotoConfirmRequest,
    MaintenanceStep,
    ManualReference,
    RetrievalCandidate,
    SessionAuditResponse,
    SessionCreateRequest,
    StepActionRequest,
)
from app.domain.enums import (
    CueType,
    IdentificationSource,
    Intent,
    SafetySeverity,
    SessionState,
)
from app.domain.kb import DEFAULT_DISCLAIMER_AR, ComponentRecord, StepRecord
from app.knowledge.loader import KnowledgeBase
from app.knowledge.retrieval import HybridRetriever, RetrievalHit
from app.safety.guard import SafetyGuard, SafetyViolation
from app.services.session import Session, SessionStore

TEXT_MATCH_MIN_SCORE = 12.0
TEXT_MATCH_MIN_GAP = 2.0
DEFAULT_BOX = (0.34, 0.30, 0.66, 0.58)

_CUE_LABELS_AR = {
    CueType.HIGHLIGHT_MESH: "حدد موضع القطعة",
    CueType.PULL_ARROW: "اسحب للخارج",
    CueType.PUSH_ARROW: "ادفع للداخل",
    CueType.ROTATE_CCW: "لف عكس عقارب الساعة",
    CueType.ROTATE_CW: "لف مع عقارب الساعة",
    CueType.DISCONNECT_PLUG: "افصل الفيش",
}


class AssistantService:
    """Orchestrates identification, safety gating, and step-by-step guidance."""

    def __init__(
        self,
        kb: KnowledgeBase,
        guard: SafetyGuard,
        retriever: HybridRetriever,
        store: SessionStore,
        vision,
        settings: Settings,
    ):
        self.kb = kb
        self.guard = guard
        self.retriever = retriever
        self.store = store
        self.vision = vision
        self.settings = settings

    # ----------------------------------------------------------------- catalog
    def list_equipment(self) -> list[EquipmentSummary]:
        summaries: list[EquipmentSummary] = []
        for name in self.kb.equipment_names():
            equipment_file = self.kb.equipment_files.get(name)
            summaries.append(
                EquipmentSummary(
                    equipment_family=name,
                    manufacturer=equipment_file.manufacturer if equipment_file else "",
                    component_count=len(self.kb.components_for(name)),
                    data_status=equipment_file.data_status if equipment_file else "sample",
                )
            )
        return summaries

    def search_components(
        self, query: str | None = None, equipment_model: str | None = None, limit: int = 20
    ) -> list[ComponentSummary]:
        if query and query.strip():
            records = [
                hit.record
                for hit in self.retriever.search(query, equipment_model, limit=limit)
            ]
        elif equipment_model:
            records = self.kb.components_for(equipment_model)[:limit]
        else:
            records = list(self.kb.components.values())[:limit]

        return [
            ComponentSummary(
                part_number=record.part_number,
                english_name=record.english_name,
                arabic_name=record.arabic_name,
                equipment_models=record.equipment_models,
                verification_status=self.kb.data_status_for(record.part_number),
            )
            for record in records
        ]

    # ----------------------------------------------------------------- session
    def create_session(self, req: SessionCreateRequest) -> AssistantResponse:
        if req.equipment_model not in self.kb.equipment:
            raise SafetyViolation(
                "unknown_equipment",
                f"المعدة ({req.equipment_model}) غير موجودة في قاعدة البيانات. "
                f"المعدات المتاحة: {', '.join(self.kb.equipment_names())}",
                status_code=404,
            )

        session = self.store.create(req.equipment_model)
        return self._build_response(
            session,
            message=(
                "بدأت جلسة العمل. وجّه الكاميرا نحو القطعة واضغط «التقاط وتحديد»، "
                "أو اختر القطعة يدويًا من القائمة."
            ),
        )

    def get_session(self, session_id: str) -> AssistantResponse:
        session = self.store.get(session_id)
        return self._build_response(session, message=self._state_message(session))

    def get_audit(self, session_id: str) -> SessionAuditResponse:
        session = self.store.get(session_id)
        return SessionAuditResponse(
            session_id=session.id,
            state=session.state,
            entries=list(session.audit),
        )

    # ----------------------------------------------------------------- identify
    async def identify(self, session_id: str, req: IdentifyRequest) -> AssistantResponse:
        session = self.store.get(session_id)
        self._reset_identification(session)
        self.store.audit(session, "identification_started", "بدأت محاولة تحديد القطعة")

        record: ComponentRecord | None = None
        source: IdentificationSource | None = None
        confidence = req.visual_confidence
        bounding_box = req.bounding_box
        candidates: list[RetrievalCandidate] = []

        if req.part_number:
            record = self.guard.require_component(req.part_number)
            source = IdentificationSource.MANUAL
            if confidence is None:
                confidence = 1.0

        elif req.image_base64:
            result = await self._run_vision(req.image_base64, session.equipment_model, req.transcript)
            candidates = []
            if result.provider.startswith("mock"):
                return self._inspection_response(
                    session,
                    "وضع الرؤية الحالي تجريبي ولا يستطيع تأكيد هوية القطعة. فعّل مزود رؤية حقيقياً ثم أعد المحاولة.",
                    event="vision_mock_abstained",
                )
            if result.error or not result.part_number:
                return self._inspection_response(
                    session,
                    "تعذر تحديد القطعة من الصورة. قرّب الكاميرا، حسّن الإضاءة، أو اختر القطعة يدويًا.",
                    event="vision_rejected",
                )
            record = self.guard.require_component(result.part_number)
            source = (
                IdentificationSource.VISION_VLM
                if not result.provider.startswith("mock")
                else IdentificationSource.VISION_MOCK
            )
            if confidence is None:
                confidence = result.confidence
            bounding_box = bounding_box or result.bounding_box

        elif req.transcript:
            match, hits = self._match_text(req.transcript, session.equipment_model)
            candidates = [self._candidate(hit) for hit in hits]
            if match is None:
                return self._inspection_response(
                    session,
                    "لم أتمكن من تحديد القطعة بدرجة كافية من النص. "
                    "قرّب الكاميرا أو اختر القطعة من النتائج المقترحة.",
                    candidates=candidates,
                    event="identification_ambiguous",
                )
            record = match
            source = IdentificationSource.TEXT_SEARCH
            if confidence is None:
                confidence = 0.9

        elif self.settings.demo_mode:
            return self._inspection_response(
                session,
                "لم تصل صورة صالحة للتعرف. التقط صورة واضحة أو استخدم مسار التصحيح اليدوي.",
                event="identification_no_input",
            )
        else:
            return self._inspection_response(
                session,
                "لم يصل إطار بصري. وجّه الكاميرا نحو القطعة ثم أعد المحاولة.",
                event="identification_no_input",
            )

        confidence = float(confidence if confidence is not None else 0.0)
        self.guard.ensure_equipment(record, session.equipment_model)

        if not self.guard.confidence_allowed(confidence):
            return self._inspection_response(
                session,
                "الرؤية غير واضحة بما يكفي لتحديد القطعة بدقة. "
                "يرجى تقريب الكاميرا أو تشغيل الإضاءة.",
                event="identification_low_confidence",
                candidates=candidates,
            )

        session.part_number = record.part_number
        session.identification_id = f"id-{secrets.token_hex(3)}"
        session.confidence = confidence
        session.bounding_box = bounding_box or DEFAULT_BOX
        session.identification_source = source
        session.loto_confirmed = False
        session.confirmed_items.clear()
        session.step_index = 1
        session.state = (
            SessionState.AWAITING_LOTO
            if record.safety.loto_required
            else SessionState.READY
            if self.guard.procedure_is_verified(record)
            else SessionState.IDENTIFIED
        )

        self.store.audit(
            session,
            "component_identified",
            f"تم تحديد {record.arabic_name} ({record.part_number}) "
            f"بثقة {confidence:.0%} عبر {source.value if source else 'unknown'}",
        )

        message = (
            f"تم تحديد {record.arabic_name} برقم {record.part_number} "
            f"بثقة {confidence:.0%}."
        )
        if not self.guard.procedure_is_verified(record):
            message += (
                " تم التعرف على القطعة ضمن بيانات التجربة، لكن مصدر الصيانة والسلامة "
                "غير معتمد لهذا الطراز؛ لن تُعرض خطوات أو عزوم حتى تتم مراجعة الدليل."
            )
        elif session.state == SessionState.AWAITING_LOTO:
            message += (
                " بوابة السلامة مغلقة الآن: أكمل بنود العزل (LOTO) على الشاشة قبل عرض خطوات الفك."
            )
        else:
            message += " يمكنك البدء بالخطوة الأولى."

        return self._build_response(
            session,
            message=message,
            candidates=candidates,
        )

    # -------------------------------------------------------------------- LOTO
    def confirm_loto(
        self, session_id: str, req: LotoConfirmRequest
    ) -> AssistantResponse:
        session = self.store.get(session_id)
        record = self._record(session)
        if record is None:
            raise SafetyViolation(
                "no_identification",
                "لا توجد قطعة محددة بعد. حدد القطعة أولًا ثم أكمل إجراءات العزل.",
                status_code=409,
            )

        if not self.guard.procedure_is_verified(record):
            self.store.audit(
                session,
                "safety_gate_blocked_unverified_source",
                f"رفض تأكيد LOTO لعدم وجود دليل سلامة معتمد للقطعة {record.part_number}",
            )
            raise SafetyViolation(
                "safety_not_verified",
                "لا يمكن فتح بوابة الصيانة؛ معلومات العزل والسلامة لهذه القطعة "
                "لم تُراجع وتُعتمد من مصدر مطابق للمعدة. لا تبدأ الفك أو التشغيل.",
                status_code=409,
            )

        requirement = record.safety
        if not requirement.loto_required:
            session.loto_confirmed = True
            session.state = SessionState.READY
            self.store.audit(session, "loto_not_required", "القطعة لا تتطلب عزلًا إلزاميًا")
            return self._build_response(
                session,
                message="هذه القطعة لا تتطلب إجراء عزل إلزامي. يمكنك البدء بالخطوة الأولى.",
            )

        required_ids = [item.id for item in requirement.checklist]
        provided = set(req.confirmed_item_ids)
        missing = [item for item in requirement.checklist if item.id not in provided]

        if missing:
            labels = "، ".join(item.label_ar for item in missing)
            self.store.audit(
                session,
                "loto_rejected",
                f"محاولة تأكيد عزل ناقصة. البنود الناقصة: {labels}",
            )
            raise SafetyViolation(
                "incomplete_checklist",
                f"لم تكتمل بنود السلامة التالية: {labels}",
                status_code=409,
            )

        session.confirmed_items = set(required_ids)
        session.loto_confirmed = True
        session.state = SessionState.READY
        session.step_index = 1
        note = f" ملاحظة الفني: {req.technician_note}" if req.technician_note else ""
        self.store.audit(
            session,
            "loto_confirmed",
            f"تم تأكيد جميع بنود العزل ({len(required_ids)} بنود) للقطعة "
            f"{record.part_number}.{note}",
        )

        first_step = record.steps[0]
        return self._build_response(
            session,
            message=(
                "تم توثيق إتمام إجراءات العزل والسلامة. "
                f"ابدأ بالخطوة 1 من {len(record.steps)}: {first_step.instruction_ar}"
            ),
        )

    # -------------------------------------------------------------------- step
    def step_action(
        self, session_id: str, req: StepActionRequest
    ) -> AssistantResponse:
        session = self.store.get(session_id)
        record = self._record(session)
        if record is None:
            raise SafetyViolation(
                "no_identification",
                "لا توجد قطعة محددة. حدد القطعة أولًا.",
                status_code=409,
            )

        self.guard.ensure_procedure_allowed(record, session.loto_confirmed)
        total = len(record.steps)
        message = ""

        if req.action == "goto":
            if req.step_index is None:
                raise SafetyViolation(
                    "missing_step_index",
                    "حدد رقم الخطوة المطلوبة.",
                    status_code=422,
                )
            session.step_index = min(max(req.step_index, 1), total)
            session.state = SessionState.IN_PROGRESS

        elif req.action == "next":
            if session.step_index >= total:
                session.state = SessionState.COMPLETED
                last = record.steps[-1]
                self.store.audit(
                    session,
                    "procedure_completed",
                    f"أنجز الفني جميع خطوات {record.part_number} ({total} خطوات)",
                )
                message = "تم إنجاز جميع الخطوات."
                if last.verification_ar:
                    message += f" {last.verification_ar}"
                return self._build_response(session, message=message)
            session.step_index += 1
            session.state = SessionState.IN_PROGRESS

        elif req.action == "prev":
            session.step_index = max(1, session.step_index - 1)
            session.state = SessionState.IN_PROGRESS

        else:  # repeat
            session.state = (
                SessionState.COMPLETED
                if session.state == SessionState.COMPLETED
                else SessionState.IN_PROGRESS
            )

        step = record.steps[session.step_index - 1]
        self.store.audit(
            session,
            "step_viewed",
            f"عرض الخطوة {session.step_index} من {total} للقطعة {record.part_number}",
        )
        message = (
            f"الخطوة {session.step_index} من {total}: {step.instruction_ar} "
            f"الأداة المطلوبة: {step.tool_required_ar}."
        )
        return self._build_response(session, message=message)

    # --------------------------------------------------------------------- ask
    def ask(self, session_id: str, req: AskRequest) -> AssistantResponse:
        session = self.store.get(session_id)
        expanded = self.retriever.expand(req.transcript)
        intent = expanded.intent
        record = self._record(session)

        if intent == Intent.CONFIRM_LOTO:
            return self._handle_loto_intent(session, record)

        if intent == Intent.NEXT_STEP:
            if session.state == SessionState.AWAITING_LOTO:
                return self._blocked_by_loto(session, record)
            if record is None:
                return self._needs_identification(session, intent)
            return self.step_action(session_id, StepActionRequest(action="next"))

        if intent == Intent.REPEAT_STEP:
            if session.state == SessionState.AWAITING_LOTO:
                return self._blocked_by_loto(session, record)
            if record is None:
                return self._needs_identification(session, intent)
            return self.step_action(session_id, StepActionRequest(action="repeat"))

        if intent == Intent.PREV_STEP:
            if session.state == SessionState.AWAITING_LOTO:
                return self._blocked_by_loto(session, record)
            if record is None:
                return self._needs_identification(session, intent)
            return self.step_action(session_id, StepActionRequest(action="prev"))

        if intent == Intent.TORQUE_QUERY:
            return self._answer_torque(session, record)

        if intent == Intent.PART_NUMBER_QUERY:
            return self._answer_part_number(session, record, req.transcript, intent)

        if intent == Intent.SAFETY_QUERY:
            return self._answer_safety(session, record)

        if intent == Intent.IDENTIFY:
            return self._answer_identify(session, record, req.transcript, intent)

        if intent == Intent.HELP:
            return self._build_response(
                session,
                message=(
                    "يمكنك قول: «الخطوة التالية»، «أعد الخطوة»، «كم العزم؟»، "
                    "«ما رقم القطعة؟»، «تحذيرات السلامة»، أو «تم العزل»."
                ),
                intent=intent,
            )

        hits = self.retriever.search(req.transcript, session.equipment_model, limit=3)
        candidates = [self._candidate(hit) for hit in hits]
        return self._build_response(
            session,
            message=(
                "لم أفهم الطلب تمامًا. جرّب: «الخطوة التالية»، «كم العزم؟»، "
                "«ما رقم القطعة؟»، أو «تحذيرات السلامة»."
            ),
            intent=intent,
            candidates=candidates,
        )

    # ------------------------------------------------------------- ask handlers
    def _handle_loto_intent(
        self, session: Session, record: ComponentRecord | None
    ) -> AssistantResponse:
        if record is None:
            return self._needs_identification(session, Intent.CONFIRM_LOTO)

        if not self.guard.procedure_is_verified(record):
            return self._build_response(
                session,
                message=(
                    "لا يمكن تأكيد العزل أو بدء الصيانة؛ بيانات السلامة الخاصة بهذه القطعة "
                    "غير معتمدة من كتيب مطابق. أوقف العمل حتى تُراجع الوثيقة والمعدة."
                ),
                intent=Intent.CONFIRM_LOTO,
                abstained=True,
                abstention_reason_ar="مصدر تعليمات السلامة غير معتمد.",
            )

        if not record.safety.loto_required:
            return self._build_response(
                session,
                message="هذه القطعة لا تتطلب إجراء عزل إلزامي. يمكنك متابعة الخطوات.",
                intent=Intent.CONFIRM_LOTO,
            )

        if session.loto_confirmed:
            return self._build_response(
                session,
                message="تم تأكيد إجراءات العزل مسبقًا. يمكنك متابعة الخطوات.",
                intent=Intent.CONFIRM_LOTO,
            )

        warnings = " ".join(record.safety.warnings_ar)
        return self._build_response(
            session,
            message=(
                "التأكيد الصوتي وحده لا يفتح بوابة السلامة. "
                "افتح قائمة السلامة على الشاشة وأكّد كل بند، ثم اضغط زر التأكيد. "
                f"التحذيرات: {warnings}"
            ),
            intent=Intent.CONFIRM_LOTO,
        )

    def _answer_torque(
        self, session: Session, record: ComponentRecord | None
    ) -> AssistantResponse:
        if record is None:
            return self._needs_identification(session, Intent.TORQUE_QUERY)

        if record.safety.loto_required and not session.loto_confirmed:
            return self._blocked_by_loto(session, record, intent=Intent.TORQUE_QUERY)

        if not self.guard.procedure_is_verified(record):
            self.store.audit(
                session,
                "torque_abstained_unverified_source",
                f"حجب قيمة العزم لعدم اعتماد المصدر للقطعة {record.part_number}",
            )
            return self._build_response(
                session,
                message=(
                    "لا أستطيع عرض عزم الشد لهذه القطعة: لا توجد قيمة عزم معتمدة "
                    "ومطابقة للموديل في مصدر تمت مراجعته. لن أعرض القيم التجريبية."
                ),
                intent=Intent.TORQUE_QUERY,
                abstained=True,
                abstention_reason_ar="قيمة عزم الشد غير معتمدة ومطابقة للطراز.",
            )

        step = record.steps[min(max(session.step_index, 1), len(record.steps)) - 1]
        if not step.requires_torque:
            message = "الخطوة الحالية لا تتطلب عزم شد."
            torque_steps = [s for s in record.steps if s.requires_torque]
            if torque_steps:
                torque_step = torque_steps[0]
                torque = self.guard.build_torque(record, torque_step)
                if torque is not None:
                    if torque.verified_from_manual:
                        message += (
                            f" عزم الربط المعتمد مذكور في الخطوة {torque_step.step_number}: "
                            f"{torque.value_nm:g} نيوتن·م ({torque.value_lbft:g} رطل·قدم) "
                            f"حسب {torque.source_document_id} صفحة {torque.source_page}."
                        )
                    else:
                        message += (
                            f" توجد قيمة تجريبية غير معتمدة في الخطوة {torque_step.step_number}: "
                            f"{torque.value_nm:g} نيوتن·م. السجل {torque.source_document_id} "
                            f"صفحة {torque.source_page} غير متحقق؛ لا تستخدم هذه القيمة في الصيانة."
                        )
                else:
                    message += (
                        f" الخطوة {torque_step.step_number} تتطلب عزمًا لكن القيمة "
                        "غير مذكورة في المصدر الموثق."
                    )
            self.store.audit(
                session, "torque_not_applicable", "استعلام عزم في خطوة لا تتطلب عزمًا"
            )
            return self._build_response(
                session, message=message, intent=Intent.TORQUE_QUERY
            )

        torque = self.guard.build_torque(record, step)
        if torque is None:
            self.store.audit(
                session,
                "torque_missing",
                f"لا توجد قيمة عزم موثقة للخطوة {step.step_number} من {record.part_number}",
            )
            return self._build_response(
                session,
                message=(
                    "قيمة عزم الشد غير مذكورة لهذه الخطوة في المصدر الموثق. "
                    "راجع جدول العزوم العام للمعدة قبل الربط، ولا تعتمد على أي قيمة تخمينية."
                ),
                intent=Intent.TORQUE_QUERY,
            )

        if torque.verified_from_manual:
            message = (
                f"عزم الشد المعتمد هو {torque.value_nm:g} نيوتن·م "
                f"({torque.value_lbft:g} رطل·قدم)."
            )
        else:
            message = (
                f"القيمة المعروضة تجريبية وغير معتمدة: {torque.value_nm:g} نيوتن·م "
                f"({torque.value_lbft:g} رطل·قدم). لا تستخدمها في صيانة فعلية."
            )
        if torque.tightening_sequence:
            message += f" {torque.tightening_sequence}"
        message += (
            f" المصدر المسجل: {torque.source_document_id} صفحة {torque.source_page}."
        )
        if not torque.verified_from_manual:
            message += " تنبيه: لم يجتز هذا السجل والمعدة تحقق المصدر المعتمد."

        self.store.audit(
            session,
            "torque_verified" if torque.verified_from_manual else "torque_sample_shown",
            f"عرض عزم {torque.value_nm:g} نيوتن·م من {torque.source_document_id} "
            f"صفحة {torque.source_page}؛ حالة التحقق: {torque.source_status}",
        )
        return self._build_response(
            session, message=message, intent=Intent.TORQUE_QUERY
        )

    def _answer_part_number(
        self,
        session: Session,
        record: ComponentRecord | None,
        transcript: str,
        intent: Intent,
    ) -> AssistantResponse:
        if record is not None:
            if self.kb.data_status_for(record.part_number) != "verified":
                message = (
                    f"تم العثور على مرشح تجريبي باسم {record.arabic_name} "
                    f"ورمز داخلي {record.part_number}. هذه البيانات غير معتمدة كرقم قطعة OEM "
                    "ولا أملك مصدرًا مطابقًا يؤكدها؛ يلزم فحص لوحة البيانات ومراجعة الكتيب."
                )
                return self._build_response(
                    session,
                    message=message,
                    intent=intent,
                    abstained=True,
                    abstention_reason_ar="هوية القطعة لم تُعتمد من مصدر الشركة المصنّعة.",
                )
            message = (
                f"رقم القطعة المعتمد هو {record.part_number}، وهي {record.arabic_name} "
                f"({record.english_name}). المرجع: {record.manual_doc_id} "
                f"صفحة {record.manual_page}."
            )
            return self._build_response(session, message=message, intent=intent)

        hits = self.retriever.search(transcript, session.equipment_model, limit=3)
        candidates = [self._candidate(hit) for hit in hits]
        message = (
            "لم يتم تحديد القطعة بعد، لذلك لا يمكنني تأكيد رقمها. "
            "أقرب النتائج معروضة للمراجعة؛ اختر القطعة الصحيحة."
        )
        if not hits:
            message = "لا توجد نتائج مطابقة. امسح لوحة بيانات المعدة أو حدد القطعة يدويًا."
        return self._build_response(
            session, message=message, intent=intent, candidates=candidates
        )

    def _answer_safety(
        self, session: Session, record: ComponentRecord | None
    ) -> AssistantResponse:
        if record is None:
            return self._build_response(
                session,
                message=(
                    "حدد القطعة أولًا لعرض تحذيرات السلامة الخاصة بها. "
                    "لا تبدأ أي فك قبل معرفة متطلبات العزل."
                ),
                intent=Intent.SAFETY_QUERY,
            )

        protocol = self.guard.build_safety(
            record, session.confirmed_items, session.loto_confirmed
        )
        if protocol is not None and protocol.source_status != "verified":
            message = (
                "لا توجد تحذيرات أو إجراءات عزل موثقة ومعتمدة ومطابقة لهذه القطعة. "
                "لا يمكنني استنتاجها أو اختراعها، ويجب إيقاف الصيانة حتى مراجعة الدليل."
            )
            return self._build_response(
                session,
                message=message,
                intent=Intent.SAFETY_QUERY,
                abstained=True,
                abstention_reason_ar="معلومات السلامة لهذه القطعة غير معتمدة من المصدر.",
            )

        requirement = record.safety
        if not requirement.warnings_ar:
            message = (
                "لا توجد تحذيرات إضافية مسجلة في المصدر المعتمد لهذه القطعة. "
                "اتبع تقييم مخاطر الموقع وتعليمات السلامة المحلية."
            )
        else:
            message = "تحذيرات السلامة المعتمدة: " + " ".join(requirement.warnings_ar)

        if requirement.loto_required and not session.loto_confirmed:
            message += " بوابة العزل ما زالت مغلقة."
        elif requirement.loto_required:
            message += " تم تأكيد إجراءات العزل."

        return self._build_response(
            session, message=message, intent=Intent.SAFETY_QUERY
        )

    def _answer_identify(
        self,
        session: Session,
        record: ComponentRecord | None,
        transcript: str,
        intent: Intent,
    ) -> AssistantResponse:
        if record is not None:
            if self.kb.data_status_for(record.part_number) != "verified":
                return self._build_response(
                    session,
                    message=(
                        f"المرشح الحالي هو {record.arabic_name} ({record.part_number}) "
                        "من قاعدة تجريبية. لم يتم توثيق هويته على هذه المعدة؛ راجع لوحة البيانات "
                        "واختر المرشح الصحيح قبل أي إجراء تشغيلي."
                    ),
                    intent=intent,
                    abstained=True,
                    abstention_reason_ar="تعذر تأكيد هوية القطعة من مصدر معتمد.",
                )
            return self._build_response(
                session,
                message=(
                    f"القطعة المحددة حاليًا هي {record.arabic_name} "
                    f"برقم {record.part_number}."
                ),
                intent=intent,
            )

        hits = self.retriever.search(transcript, session.equipment_model, limit=3)
        candidates = [self._candidate(hit) for hit in hits]
        if hits:
            message = (
                "لا أستطيع تأكيد القطعة من الوصف وحده. "
                "أقرب النتائج معروضة؛ اختر القطعة الصحيحة أو وجّه الكاميرا إليها."
            )
        else:
            message = "لم أجد نتائج مطابقة. وجّه الكاميرا نحو القطعة أو اكتب رقمها."
        return self._build_response(
            session, message=message, intent=intent, candidates=candidates
        )

    # ----------------------------------------------------------------- helpers
    def _match_text(
        self, transcript: str, equipment_model: str
    ) -> tuple[ComponentRecord | None, list[RetrievalHit]]:
        hits = self.retriever.search(transcript, equipment_model, limit=3)
        if not hits:
            return None, []
        top = hits[0]
        second_score = hits[1].score if len(hits) > 1 else 0.0
        if top.score >= TEXT_MATCH_MIN_SCORE and (top.score - second_score) >= TEXT_MATCH_MIN_GAP:
            return top.record, hits
        return None, hits

    async def _run_vision(
        self, image_base64: str, equipment_model: str, hint: str | None
    ) -> VisionResult:
        try:
            return await self.vision.identify(image_base64, equipment_model, hint)
        except Exception as exc:  # pragma: no cover - defensive
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider="error",
                error=str(exc),
            )

    def _record(self, session: Session) -> ComponentRecord | None:
        if not session.part_number:
            return None
        return self.kb.get_component(session.part_number)

    def _reset_identification(self, session: Session) -> None:
        session.part_number = None
        session.identification_id = None
        session.confidence = 0.0
        session.bounding_box = None
        session.identification_source = None
        session.loto_confirmed = False
        session.confirmed_items.clear()
        session.step_index = 1
        session.state = SessionState.CREATED

    def _needs_identification(
        self, session: Session, intent: Intent
    ) -> AssistantResponse:
        return self._build_response(
            session,
            message=(
                "لم يتم تحديد قطعة بعد. وجّه الكاميرا نحو القطعة واضغط «التقاط وتحديد»، "
                "أو اخترها من قائمة القطع."
            ),
            intent=intent,
        )

    def _blocked_by_loto(
        self,
        session: Session,
        record: ComponentRecord | None,
        intent: Intent | None = None,
    ) -> AssistantResponse:
        if record is None or not self.guard.procedure_is_verified(record):
            return self._build_response(
                session,
                message=(
                    "إيقاف آمن: لا توجد تعليمات عزل وسلامة معتمدة ومطابقة لهذه القطعة. "
                    "لن أعرض تحذيرات أو إجراءات LOTO تجريبية؛ لا تبدأ الصيانة حتى مراجعة الدليل الصحيح."
                ),
                intent=intent,
                abstained=True,
                abstention_reason_ar="معلومات العزل والسلامة غير معتمدة لهذه المعدة.",
            )

        warnings = " ".join(record.safety.warnings_ar)
        return self._build_response(
            session,
            message=(
                "بوابة السلامة مغلقة. أكمل جميع بنود العزل (LOTO) على الشاشة "
                f"قبل عرض الخطوات أو قيم العزم. {warnings}"
            ),
            intent=intent,
        )

    def _inspection_response(
        self,
        session: Session,
        message: str,
        event: str,
        candidates: list[RetrievalCandidate] | None = None,
    ) -> AssistantResponse:
        session.state = SessionState.CREATED
        self.store.audit(session, event, message)
        return self._build_response(
            session,
            message=message,
            candidates=candidates or [],
            inspection_prompt=message,
            abstained=True,
            abstention_reason_ar=message,
        )

    def _candidate(self, hit: RetrievalHit) -> RetrievalCandidate:
        return RetrievalCandidate(
            part_number=hit.record.part_number,
            arabic_name=hit.record.arabic_name,
            english_name=hit.record.english_name,
            score=round(hit.score, 1),
        )

    def _state_message(self, session: Session) -> str:
        if session.state == SessionState.CREATED:
            return "الجلسة جاهزة. حدد القطعة للبدء."
        if session.state == SessionState.IDENTIFIED:
            return "تم اختيار مرشح للقطعة، لكن إرشادات الصيانة غير معتمدة."
        if session.state == SessionState.AWAITING_LOTO:
            return "تم تحديد القطعة. أكمل بنود السلامة قبل عرض خطوات الفك."
        if session.state == SessionState.READY:
            return "السلامة مؤكدة. يمكنك البدء بالخطوة الأولى."
        if session.state == SessionState.IN_PROGRESS:
            return f"أنت في الخطوة {session.step_index}."
        return "تم إنجاز الإجراء. راجع خطوة التحقق النهائية."

    def _default_actions(self, session: Session, record: ComponentRecord | None) -> list[str]:
        if session.state == SessionState.CREATED:
            return [
                "وجّه الكاميرا نحو القطعة ثم اضغط «التقاط وتحديد»",
                "أو اكتب رقم القطعة/اسمها للبحث اليدوي",
            ]
        if session.state == SessionState.AWAITING_LOTO:
            if record is not None and not self.guard.procedure_is_verified(record):
                return ["راجع حالة اعتماد المصدر", "تحذيرات السلامة", "اعرض القطع"]
            return [
                "أكمل جميع بنود العزل في لوحة السلامة",
                "لا تبدأ الفك قبل تأكيد البوابة",
            ]
        if session.state in (SessionState.READY, SessionState.IN_PROGRESS):
            if record is not None and self.guard.procedure_is_verified(record):
                return [
                    "قل: «الخطوة التالية»",
                    "قل: «أعد الخطوة»",
                    "قل: «كم العزم؟»",
                ]
            return ["راجع حالة اعتماد المصدر", "تحذيرات السلامة", "اعرض القطع"]
        if session.state == SessionState.IDENTIFIED:
            return ["راجع حالة اعتماد المصدر", "تحذيرات السلامة", "اعرض القطع"]
        if session.state == SessionState.COMPLETED:
            return ["ابدأ جلسة جديدة", "راجع سجل الجلسة (Audit)"]
        return []

    def _build_response(
        self,
        session: Session,
        message: str,
        intent: Intent | None = None,
        candidates: list[RetrievalCandidate] | None = None,
        inspection_prompt: str | None = None,
        abstained: bool = False,
        abstention_reason_ar: str | None = None,
    ) -> AssistantResponse:
        record = self._record(session)
        identified = None
        safety = None
        current_step = None
        manual_reference = None
        disclaimer = DEFAULT_DISCLAIMER_AR
        data_status = "sample"
        procedure_available = bool(
            record is not None and self.guard.procedure_is_verified(record)
        )
        procedure_blocked_reason = (
            None
            if procedure_available or record is None
            else "لا توجد وثيقة صيانة وسلامة مطابقة ومعتمدة لهذه القطعة. تم حجب الخطوات والعزم."
        )

        if record is not None:
            data_status = self.kb.data_status_for(record.part_number)
            disclaimer = self.kb.disclaimer_for(record.part_number) or disclaimer
            box = session.bounding_box or DEFAULT_BOX
            identified = IdentifiedComponent(
                part_number=record.part_number,
                english_name=record.english_name,
                arabic_name=record.arabic_name,
                confidence_score=session.confidence,
                bounding_box_2d=box,
                identification_source=session.identification_source
                or IdentificationSource.MANUAL,
                verification_status=data_status,
            )
            safety = self.guard.build_safety(
                record, session.confirmed_items, session.loto_confirmed
            )

            if procedure_available and session.state in (
                SessionState.READY,
                SessionState.IN_PROGRESS,
                SessionState.COMPLETED,
            ) and (not record.safety.loto_required or session.loto_confirmed):
                step_record = record.steps[
                    min(max(session.step_index, 1), len(record.steps)) - 1
                ]
                current_step = self._build_step(record, step_record)
                manual_reference = ManualReference(
                    document_id=record.manual_doc_id,
                    page_number=record.manual_page,
                    section_title=record.section_title,
                    verification_status=data_status,
                )

        return AssistantResponse(
            session_id=session.id,
            identification_id=session.identification_id,
            state=session.state,
            equipment_model=session.equipment_model,
            requires_closer_inspection=inspection_prompt is not None,
            inspection_prompt_ar=inspection_prompt,
            identified_component=identified,
            safety_lockout=safety,
            current_step=current_step,
            manual_reference=manual_reference,
            assistant_message_ar=message,
            next_actions_ar=self._default_actions(session, record),
            data_disclaimer_ar=disclaimer,
            retrieval_candidates=candidates or [],
            last_intent=intent,
            procedure_available=procedure_available,
            procedure_blocked_reason_ar=procedure_blocked_reason,
            abstained=abstained,
            abstention_reason_ar=abstention_reason_ar,
        )

    def _build_step(
        self, record: ComponentRecord, step_record: StepRecord
    ) -> MaintenanceStep:
        torque = self.guard.build_torque(record, step_record)
        cue_type = step_record.cue.cue_type or CueType.HIGHLIGHT_MESH
        return MaintenanceStep(
            step_number=step_record.step_number,
            total_steps=len(record.steps),
            instruction_ar=step_record.instruction_ar,
            tool_required_ar=step_record.tool_required_ar,
            torque_spec=torque,
            warning_ar=step_record.warning_ar,
            verification_ar=step_record.verification_ar,
            ar_visual_cue=ARVisualCue(
                cue_type=cue_type,
                direction=step_record.cue.direction,
                color_hex=step_record.cue.color_hex,
                label_ar=_CUE_LABELS_AR.get(cue_type, "حدد موضع القطعة"),
            ),
        )
