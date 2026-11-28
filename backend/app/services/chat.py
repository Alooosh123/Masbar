from __future__ import annotations

import logging
import re

from app.adapters.chat.cohere_chat import CohereChatAdapter
from app.core.arabic import normalize_arabic, term_in_text, tokenize
from app.core.config import Settings
from app.domain.api_models import (
    AskRequest,
    ChatRequest,
    ChatResponse,
    ComponentSummary,
    EquipmentSummary,
    IdentifyRequest,
    SessionCreateRequest,
)
from app.domain.enums import SessionState
from app.domain.kb import ComponentRecord
from app.knowledge.loader import KnowledgeBase
from app.safety.guard import SafetyViolation
from app.safety.output import sanitize_user_facing_text
from app.services.assistant import AssistantService
from app.services.session import Session, SessionNotFound, SessionStore
from app.adapters.vision.equipment import EquipmentVisionAdapter

logger = logging.getLogger(__name__)

_STATE_AR: dict[SessionState, str] = {
    SessionState.PENDING_CONFIRMATION: "بانتظار تأكيد المعدة",
    SessionState.CREATED: "بانتظار تحديد القطعة",
    SessionState.IDENTIFIED: "تم التحديد",
    SessionState.AWAITING_LOTO: "بانتظار تأكيد العزل",
    SessionState.READY: "جاهز للتنفيذ",
    SessionState.IN_PROGRESS: "قيد التنفيذ",
    SessionState.COMPLETED: "مكتمل",
}

# Aliases are matched after Arabic normalization (ة → ه, أ/إ/آ → ا).
_EQUIPMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Caterpillar C15 ACERT": (
        "c15",
        "acert",
        "محرك c15",
        "كاتربلر c15",
        "محرك الديزل c15",
    ),
    "Siemens S7-1200 Control Panel": (
        "s7",
        "s7-1200",
        "s7 1200",
        "siemens",
        "سيمنز",
        "لوحه التحكم",
        "لوحه كهربائيه",
        "control panel",
    ),
}

_OPEN_CAMERA_VERBS = {"افتح", "فتح", "شغل", "شغلي", "ابدأ", "التقط", "خذ", "صور"}
_CLOSE_CAMERA_VERBS = {"اغلق", "غلق", "اقفل", "سكر", "اطفي", "اوقف", "أغلق"}
_START_MIC_WORDS = {"ميكروفون", "مايك", "استمع", "اسمع", "اسمعني", "ابدأ"}
_STOP_MIC_WORDS = {"اوقف", "اطفي", "اغلق", "سكر", "اسكت", "توقف", "كفى"}
_CLOSE_WORDS = {"اغلق", "غلق", "اقفل", "سكر", "اطفي", "اوقف"}

_GROUNDED_TERMS = (
    # Torque and fastening values
    "عزم",
    "عزم الشد",
    "نيوتن",
    "رطل",
    "torque",
    # Procedure and steps
    "خطوه",
    "خطوات",
    "step",
    "افك",
    "فك",
    "فكها",
    "فكه",
    "تركيب",
    "اركب",
    "استبدال",
    "استبدل",
    "اغير",
    "تغيير",
    "اصلاح",
    "كيف اصلح",
    "ضغط منخفض",
    "ضغط عالي",
    "ضعف ضغط",
    "تسريب زيت",
    "تسرب زيت",
    "تهريب",
    "حراره عاليه",
    "ارتفاع الحراره",
    "سخونه",
    "سخونة",
    "اهتزاز غير طبيعي",
    "صوت غريب",
    "رائحه احتراق",
    "دخان",
    "المحرك لا يعمل",
    "ما يشتغل",
    "المضخه متوقفه",
    "لا يدور",
    "leak",
    "pressure drop",
    "low pressure",
    "overheating",
    "abnormal vibration",
    "unusual noise",
    "burning smell",
    "smoke",
    "not starting",
    "not running",
    "malfunction",
    "fault",
    "repair",
    "troubleshoot",
    "اجراء",
    "اجراءات",
    "طريقه فك",
    "طريقه تركيب",
    "طريقه استبدال",
    "طريقه عزل",
    "كيف افك",
    "كيف اركب",
    "كيف اغير",
    "افصل",
    "وصل",
    "اربط",
    "ربط",
    "اشد",
    # Safety and LOTO
    "سلامه",
    "عزل",
    "لوتو",
    "قفل",
    "تحذير",
    "تحذيرات",
    "خطر",
    "مخاطر",
    "loto",
    "تم العزل",
    "اكملت العزل",
    "قفلت",
    # Part identity
    "رقم القطعه",
    "رقم قطع",
    "part number",
)

_COMMAND_STOPWORDS = {
    "حدد",
    "تحديد",
    "تعرف",
    "اعرف",
    "القطعه",
    "قطعه",
    "من",
    "فضلك",
    "لو",
    "سمحت",
    "هذه",
    "هذا",
    "الصوره",
    "صوره",
    "في",
    "على",
    "علي",
    "كاميرا",
    "افتح",
    "الان",
    "لي",
    "هل",
    "يمكنك",
    "اريد",
    "ابغى",
    "ابي",
    "هيا",
    "قم",
}

_HELP_TERMS = ("مساعده", "مساعدة", "help", "ماذا تستطيع", "وش تستطيع", "شنو تقدر")


class ChatService:
    """Coordinate equipment identification, manual-grounded maintenance, and abstention.

    General-purpose chat and free-form image description are intentionally
    outside the MISBAR MVP.
    """

    def __init__(
        self,
        assistant: AssistantService,
        kb: KnowledgeBase,
        store: SessionStore,
        chat: CohereChatAdapter | None,
        settings: Settings,
        equipment_vision: EquipmentVisionAdapter | None = None,
    ):
        self.assistant = assistant
        self.kb = kb
        self.store = store
        self.chat = chat
        self.settings = settings
        self.equipment_vision = equipment_vision

    # ------------------------------------------------------------------ public
    async def handle(self, req: ChatRequest) -> ChatResponse:
        message = (req.message or "").strip()
        session = self._load_session(req.session_id)
        has_image = bool(req.image_base64)

        if has_image:
            return await self._identify_equipment(req.image_base64)

        if session is not None and message.strip():
            normalized_confirmation = normalize_arabic(message).strip().casefold()
            confirmation_phrases = {
                "تأكيد المعدة", "اكد المعدة", "نعم اكد", "نعم صحيحة",
                "صحيح", "confirm equipment", "confirm", "yes confirm",
            }
            if normalized_confirmation in {
                normalize_arabic(item).casefold() for item in confirmation_phrases
            }:
                if session.state == SessionState.PENDING_CONFIRMATION:
                    return self._handle_pending_equipment_confirmation(session, message)
                return ChatResponse(
                    message_ar=f"المعدة {session.equipment_model} مؤكدة بالفعل.",
                    source="system",
                    session=self._safe_session(session),
                    quick_replies=["اسأل عن الصيانة", "افتح الكاميرا"],
                )

        if session is not None and session.state == SessionState.PENDING_CONFIRMATION:
            return self._handle_pending_equipment_confirmation(session, message)

        if not message:
            return self._welcome()

        if self._is_close_camera(message):
            return ChatResponse(
                message_ar="تم إغلاق الكاميرا. يمكنك متابعة المحادثة أو كتابة طلبك.",
                source="system",
                action="close_camera",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
            )

        if self._is_open_camera(message):
            return ChatResponse(
                message_ar=(
                    "فتحت الكاميرا لتحديد نوع المعدة المدعومة. التقط صورة واضحة، راجع النتيجة، ثم أكدها."
                ),
                source="system",
                action="open_camera",
                session=self._safe_session(session),
                quick_replies=["التقط صورة للمعدة"],
            )

        if self._is_stop_listening(message):
            return ChatResponse(
                message_ar="أوقفت الاستماع. يمكنك الكتابة أو الضغط على الميكروفون متى أردت.",
                source="system",
                action="stop_listening",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
            )

        if self._is_start_listening(message):
            return ChatResponse(
                message_ar="الميكروفون جاهز. تكلّم الآن وسأحوّل كلامك إلى طلب.",
                source="system",
                action="start_listening",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
            )

        if self._is_help(message):
            return self._help(session)

        # Manual search and generation are opt-in and protected by authenticated
        # API access. The ingestion route independently enforces owner/admin roles.
        if self._is_manual_search(message):
            if not self.settings.manual_search_available:
                return ChatResponse(
                    message_ar=(
                        "بحث الكتيبات معطل افتراضياً لحماية محتوى الأدلة. لا تعرض الخادم للإنترنت قبل إضافة المصادقة والصلاحيات؛ لم أقدم معلومات صيانة غير موثقة."
                    ),
                    source="system",
                    session=self._safe_session(session),
                    quick_replies=self._base_quick_replies(session),
                    abstained=True,
                    abstention_reason_ar="خدمة البحث في الكتيبات غير مفعلة.",
                )
            return await self._manual_search_reply(session, message)

        # Maintenance questions that are not handled by deterministic safety
        # commands must use the approved manual index, never general chat.
        if self._is_maintenance_query(message):
            if session is None:
                equipment = self.assistant.list_equipment()
                return ChatResponse(
                    message_ar=(
                        "أحتاج أولاً إلى صورة وتأكيد المعدة حتى أبحث في دليلها المعتمد. "
                        "لا أستخدم قاعدة معرفة عامة لإعطاء معلومات صيانة."
                    ),
                    source="system",
                    equipment=equipment,
                    quick_replies=self._equipment_quick_replies(equipment),
                    abstained=True,
                    abstention_reason_ar="لا توجد معدة مؤكدة لتقييد البحث في دليلها.",
                )
            if not self.settings.manual_search_available:
                return ChatResponse(
                    message_ar=(
                        "البحث في دليل الصيانة غير متاح حالياً. لم أستخدم المحادثة العامة "
                        "لإعطاء معلومات صيانة؛ تحقق من إعدادات الوصول ثم أعد السؤال."
                    ),
                    source="system",
                    session=self._safe_session(session),
                    quick_replies=self._base_quick_replies(session),
                    abstained=True,
                    abstention_reason_ar="خدمة البحث في دليل الصيانة غير مفعلة.",
                )
            return await self._manual_search_reply(session, message)

        # Safety-critical deterministic commands continue through the existing
        # verified knowledge/safety gate.
        if self._needs_grounded_answer(message):
            return self._grounded_reply(session, message)

        # OEM registry and data-provenance questions remain available as
        # read-only reference information; they do not create equipment sessions
        # or authorize maintenance instructions.
        if self._is_manufacturer_list(message):
            return self._manufacturer_catalog(session)

        if self._is_oem_data_question(message):
            return self._oem_data_status(session)

        if self._is_equipment_list(message):
            return self._equipment_catalog()

        if self._is_start_session(message):
            return self._start_session(message, session)

        return await self._general_reply(req, session, message)

    # --------------------------------------------------------------- greetings
    def _welcome(self) -> ChatResponse:
        equipment = self.assistant.list_equipment()
        return ChatResponse(
            message_ar=(
                "مرحبًا! أنا مسبار. أساعدك في تحديد المعدات المدعومة من الصورة، "
                "ثم أبحث عن معلومات الصيانة في دليل OEM المطابق. إذا كانت الصورة أو الأدلة غير كافية، "
                "سأوضح ذلك دون تخمين.\n\nابدأ بالتقاط صورة واضحة للمعدة."
            ),
            source="system",
            equipment=equipment,
            quick_replies=self._equipment_quick_replies(equipment)
            + ["افتح الكاميرا", "شغّل الميكروفون"],
        )

    def _help(self, session: Session | None) -> ChatResponse:
        return ChatResponse(
            message_ar=(
                "يمكنني تنفيذ هذه الطلبات من داخل المحادثة:\n"
                "• التقط صورة للمعدة لتحديدها ثم أكد النتيجة\n"
                "• اسأل سؤال صيانة بعد تأكيد المعدة\n"
                "• «ابحث في الكتيبات عن …» لاسترجاع مقتطفات الدليل المطابق\n"
                "• «تحذيرات السلامة»، «كم العزم؟»، «الخطوة التالية»\n\n"
                "أسئلة العزم والفك والعزل لا يجيب عنها إلا محرك قاعدة المعرفة "
                "بعد تحديد المعدة والقطعة."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=self._base_quick_replies(session),
        )

    # ---------------------------------------------------------------- catalogs
    def _equipment_catalog(self) -> ChatResponse:
        equipment = self.assistant.list_equipment()
        return ChatResponse(
            message_ar=self._equipment_text(equipment),
            source="system",
            equipment=equipment,
            quick_replies=self._equipment_quick_replies(equipment),
        )

    def _manufacturer_catalog(self, session: Session | None = None) -> ChatResponse:
        # Imported lazily to avoid a deps <-> chat import cycle.
        from app.deps import get_oem_registry

        registry = get_oem_registry()
        lines = [
            f"• {item.name_ar} ({item.name_en}) — {item.country_ar} — "
            f"{len(item.model_families)} عائلات موديلات"
            for item in registry.manufacturers
        ]
        return ChatResponse(
            message_ar=(
                f"سجل مصادر OEM الرسمي يحتوي {registry.count} شركة من مصنّعي "
                "المعدات الثقيلة:\n"
                + "\n".join(lines)
                + "\n\nهذه روابط وموديلات كتالوج عامة من المواقع الرسمية. "
                "قيم العزم وخطوات الفك وبنود LOTO لا تُعرض إلا بعد استيراد "
                "كتيب خدمة OEM معتمد ومُتحقق منه."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=[
                "ما المعدات المتاحة؟",
                "كيف أضيف بيانات OEM؟",
                "افتح الكاميرا",
            ],
        )

    def _oem_data_status(self, session: Session | None) -> ChatResponse:
        from app.deps import get_oem_registry

        registry = get_oem_registry()
        sample_count = len(self.kb.components)
        return ChatResponse(
            message_ar=(
                f"حالة البيانات الآن:\n"
                f"• سجل OEM الرسمي: {registry.count} شركة مع روابط المواقع "
                "الرسمية وعائلات الموديلات.\n"
                f"• قاعدة الصيانة الحالية: {sample_count} قطعة تجريبية "
                "(data_status=sample) وليست كتيبات مصنّع.\n\n"
                "لا يمكن استبدال العزم وخطوات الفك وLOTO ببيانات «حقيقية» دون "
                "كتيب خدمة OEM معتمد. أضفت مسار استيراد يرفض أي سجل بلا "
                "source_document_id وsource_page وverified_from_manual=true. "
                "راجع docs/OEM_DATA.md."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=[
                "ما الشركات المتاحة؟",
                "ما المعدات المتاحة؟",
                "افتح الكاميرا",
            ],
        )

    def _component_catalog(self, session: Session | None) -> ChatResponse:
        if session is None:
            return self._ask_for_equipment("لعرض القطع المسجلة، اختر المعدة أولًا:")
        components = self._component_summaries(session.equipment_model)
        if not components:
            return self._system_reply(
                "لا توجد قطع مسجلة لهذه المعدة في قاعدة البيانات.", session
            )
        lines = [
            f"• {item.part_number} — {item.arabic_name} ({item.english_name})"
            for item in components
        ]
        return ChatResponse(
            message_ar=(
                f"القطع المسجلة لمعدة {session.equipment_model} ({len(components)}):\n"
                + "\n".join(lines)
                + "\nاختر قطعة بالضغط على الزر أو اكتب رقمها."
            ),
            source="system",
            session=self._safe_session(session),
            components=components,
            quick_replies=[f"حدد القطعة {item.part_number}" for item in components[:6]]
            + ["افتح الكاميرا"],
        )

    def _start_session(self, message: str, session: Session | None) -> ChatResponse:
        normalized = normalize_arabic(message).lower()
        if "320d" in normalized.replace(" ", ""):
            equipment = self.assistant.list_equipment()
            return ChatResponse(
                message_ar=(
                    "المعدة Caterpillar 320D غير مدعومة حالياً. لا يمكن إنشاء جلسة لها. "
                    "التقط صورة لمعدة مدعومة حتى يحددها النظام ويعرضها للتأكيد.\n\n"
                    + self._equipment_text(equipment)
                ),
                source="system",
                session=self._safe_session(session),
                equipment=equipment,
                quick_replies=["افتح الكاميرا"],
                abstained=True,
                abstention_reason_ar="Caterpillar 320D خارج قائمة المعدات المدعومة.",
            )
        return ChatResponse(
            message_ar=(
                "لا تبدأ جلسة الصيانة باختيار يدوي. التقط صورة للمعدة أولاً؛ "
                "يمكنك تصحيح نتيجة التعرف يدوياً بعد أن يعرضها النظام للتأكيد."
            ),
            source="system",
            session=self._safe_session(session),
            action="open_camera",
            quick_replies=["افتح الكاميرا"],
            abstained=True,
            abstention_reason_ar="يجب أن يبدأ تحديد المعدة بالصورة.",
        )

    # ------------------------------------------------ equipment identification
    async def _identify_equipment(self, image_base64: str | None) -> ChatResponse:
        """Identify an equipment model from an image and create a pending session.

        A real equipment-level vision provider is mandatory. The component-level
        mock adapter is deliberately not used as a fallback for equipment identity.
        """
        equipment = self.assistant.list_equipment()
        if not image_base64 or not image_base64.strip():
            return ChatResponse(
                message_ar="لم تصل صورة صالحة. التقط صورة واضحة للمعدة ثم أرسلها مجدداً.",
                source="system",
                equipment=equipment,
                quick_replies=["افتح الكاميرا"],
                abstained=True,
                abstention_reason_ar="الصورة مفقودة أو فارغة.",
            )

        if self.equipment_vision is None:
            return ChatResponse(
                message_ar=(
                    "التعرف البصري الحقيقي غير مهيأ حالياً. لم أستخدم المحاكاة "
                    "ولم أنشئ جلسة. فعّل مزود رؤية حقيقياً ثم أعد إرسال الصورة."
                ),
                source="system",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="مزود التعرف البصري الحقيقي غير مهيأ.",
            )

        try:
            result = await self.equipment_vision.identify(
                image_base64, self.kb.equipment_names()
            )
        except Exception:
            logger.exception("Equipment-level vision request failed")
            return ChatResponse(
                message_ar="تعذر الاتصال بخدمة التعرف البصري. لم يتم إنشاء جلسة؛ أعد المحاولة لاحقاً.",
                source="system",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="فشل تقني في خدمة التعرف البصري.",
            )

        if result.error:
            invalid_image = result.error in {
                "image_required",
                "invalid_or_oversized_image",
            }
            unsupported = result.error == "unsupported_equipment_result"
            if invalid_image:
                message = "الصورة غير صالحة أو يتجاوز حجمها الحد المسموح. التقط صورة JPEG أو PNG أو WebP أصغر ثم أعد المحاولة."
                reason = "صورة غير صالحة أو كبيرة جداً."
            elif result.error == "unclear_image":
                message = "لم أتمكن من تحديد المعدة من الصورة بوضوح. أعد التصوير مع إظهار المعدة ولوحة بياناتها."
                reason = "الصورة غير واضحة بما يكفي للتعرف."
            elif unsupported:
                message = "لم تطابق الصورة أياً من المعدات المدعومة. لا يمكنني إسنادها إلى طراز آخر بالتخمين."
                reason = "المعدة الظاهرة غير مدعومة أو لم تطابق القائمة المغلقة."
            elif result.error == "vision_payment_or_quota_required":
                message = "خدمة الرؤية تحتاج رصيدًا أو تجاوزت الحصة المجانية. لم أنشئ جلسة؛ حاول لاحقًا أو أبلغ مسؤول النظام."
                reason = "رصيد أو حصة API غير متاحة."
            elif result.error == "vision_api_key_invalid":
                message = "مفتاح مزود الرؤية غير صالح أو غير مصرح. لم أنشئ جلسة؛ أبلغ مسؤول النظام."
                reason = "مشكلة اعتماد API."
            elif result.error == "vision_rate_limited":
                message = "وصلنا إلى حد طلبات مزود الرؤية مؤقتًا. انتظر قليلًا ثم أعد المحاولة."
                reason = "تجاوز حد الطلبات."
            elif result.error == "vision_timeout":
                message = "انتهت مهلة التعرف البصري. لم أنشئ جلسة؛ أعد المحاولة."
                reason = "انتهت مهلة مزود الرؤية."
            elif result.error == "vision_provider_unavailable":
                message = "مزود الرؤية غير متاح مؤقتًا. لم أنشئ جلسة؛ أعد المحاولة لاحقًا."
                reason = "مزود الرؤية غير متاح."
            elif result.error == "vision_network_error":
                message = "تعذر الاتصال بمزود الرؤية. لم أنشئ جلسة؛ تحقق من الخدمة ثم أعد المحاولة."
                reason = "فشل الاتصال بمزود الرؤية."
            else:
                message = "تعذر إكمال التعرف البصري بسبب استجابة غير صالحة أو عطل بالخدمة. لم أنشئ جلسة؛ أعد المحاولة لاحقًا."
                reason = "فشل تقني أو استجابة غير صالحة من مزود الرؤية."
            return ChatResponse(
                message_ar=message,
                source="system",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar=reason,
            )

        candidate = result.equipment_model
        confidence = result.confidence
        if candidate not in self.kb.equipment:
            return ChatResponse(
                message_ar="لم أتمكن من تحديد معدة مدعومة بثقة كافية. حسّن الإضاءة وأظهر لوحة بيانات المعدة ثم أعد التصوير.",
                source="system",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="لم ينتج نموذج الرؤية معدة مطابقة لقائمة المعدات المعتمدة.",
            )

        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.0 <= confidence <= 1.0:
            return ChatResponse(
                message_ar="أعاد مزود الرؤية درجة ثقة غير صالحة. لم يتم إنشاء جلسة؛ أعد المحاولة لاحقاً.",
                source="system",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="درجة الثقة المرسلة من مزود الرؤية غير صالحة.",
            )

        if confidence < self.settings.min_visual_confidence:
            return ChatResponse(
                message_ar=(
                    f"النتيجة المحتملة هي {candidate}، لكن الثقة ({confidence:.0%}) "
                    "أقل من الحد المطلوب. لم أعتمد المعدة؛ أعد التصوير من زاوية أوضح."
                ),
                source="vision",
                equipment=equipment,
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="ثقة التعرف أقل من الحد المعتمد.",
            )

        pending = self.assistant.create_session(
            SessionCreateRequest(equipment_model=candidate)
        )
        session = self._load_session(pending.session_id)
        return ChatResponse(
            message_ar=(
                f"يُرجّح أن المعدة هي {candidate} بدرجة ثقة {confidence:.0%}. "
                "هذه نتيجة مقترحة وليست تأكيداً نهائياً. راجع الطراز ثم أرسل «تأكيد المعدة» "
                "لتفعيل سياق الصيانة، أو أعد التصوير إذا كانت النتيجة غير صحيحة."
            ),
            source="vision",
            session=self._safe_session(session),
            equipment=equipment,
            quick_replies=["تأكيد المعدة", "إعادة التصوير"],
        )

    def _handle_pending_equipment_confirmation(
        self, session: Session, message: str
    ) -> ChatResponse:
        """Require an explicit confirmation before activating the equipment context."""
        normalized = normalize_arabic(message).strip()
        tokens = set(tokenize(normalized))
        confirm_phrases = {
            "تأكيد المعدة",
            "اكد المعدة",
            "نعم اكد",
            "نعم صحيحة",
            "صحيح",
            "confirm equipment",
            "confirm",
            "yes confirm",
        }
        reject_phrases = {
            "لا",
            "غير صحيح",
            "ليست صحيحة",
            "اعد التصوير",
            "اعادة التصوير",
            "إعادة التصوير",
            "retake",
            "no",
        }

        is_confirm = normalized.casefold() in {
            normalize_arabic(item).casefold() for item in confirm_phrases
        }
        is_reject = normalized.casefold() in {
            normalize_arabic(item).casefold() for item in reject_phrases
        }
        corrected_model = self._find_equipment(message)
        correction_intent = bool(
            tokens & {"بل", "اقصد", "اقصد ان", "المعده", "المعده هي"}
        ) or "المعدة هي" in message
        if correction_intent and corrected_model and corrected_model != session.equipment_model:
            previous = session.equipment_model
            session.equipment_model = corrected_model
            self.store.audit(
                session,
                "equipment_candidate_corrected",
                f"صحح المستخدم المعدة المقترحة من {previous} إلى {corrected_model}؛ التأكيد ما زال مطلوباً.",
            )
            return ChatResponse(
                message_ar=(
                    f"تم تحديث النتيجة المقترحة إلى {corrected_model}. "
                    "لم يتم تفعيلها بعد؛ أرسل «تأكيد المعدة» لقبولها أو أعد التصوير."
                ),
                source="vision",
                session=self._safe_session(session),
                quick_replies=["تأكيد المعدة", "إعادة التصوير"],
            )

        if is_confirm:
            session.state = SessionState.CREATED
            self.store.audit(
                session,
                "equipment_confirmed",
                f"أكد المستخدم هوية المعدة المقترحة: {session.equipment_model}.",
            )
            return ChatResponse(
                message_ar=(
                    f"تم تأكيد {session.equipment_model}. أصبح سياق المعدة نشطاً. "
                    "يمكنك الآن طرح سؤال صيانة؛ سأستخدم الدليل المعتمد المطابق فقط."
                ),
                source="system",
                session=self._safe_session(session),
                quick_replies=["اسأل عن الصيانة", "افتح الكاميرا"],
            )

        if is_reject:
            return ChatResponse(
                message_ar=(
                    f"لم يتم اعتماد {session.equipment_model}. أعد تصوير المعدة بوضوح؛ "
                    "لن أفعّل سياق الصيانة قبل تأكيد نتيجة صحيحة."
                ),
                source="system",
                session=self._safe_session(session),
                action="open_camera",
                quick_replies=["إعادة التصوير"],
                abstained=True,
                abstention_reason_ar="رفض المستخدم نتيجة التعرف؛ التأكيد ما زال مطلوباً.",
            )

        # Repeated confirmation is safe and does not create another audit event.
        if session.state != SessionState.PENDING_CONFIRMATION:
            return ChatResponse(
                message_ar=f"المعدة {session.equipment_model} مؤكدة بالفعل.",
                source="system",
                session=self._safe_session(session),
                quick_replies=["اسأل عن الصيانة", "افتح الكاميرا"],
            )

        return ChatResponse(
            message_ar=(
                f"المعدة المقترحة هي {session.equipment_model}. لم يتم تأكيدها بعد. "
                "أرسل «تأكيد المعدة» لقبولها أو «إعادة التصوير» إذا كانت غير صحيحة. "
                "لن أجيب عن أسئلة الصيانة قبل التأكيد."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=["تأكيد المعدة", "إعادة التصوير"],
            abstained=True,
            abstention_reason_ar="المعدة بانتظار تأكيد المستخدم.",
        )

    # ------------------------------------------------------------- identification
    async def _identify(
        self,
        req: ChatRequest,
        session: Session | None,
        message: str,
        from_image: bool,
    ) -> ChatResponse:
        part = self._find_part(message)
        if session is None:
            equipment_name = self._find_equipment(message)
            if part is not None and part.equipment_models:
                equipment_name = part.equipment_models[0]
            if equipment_name is None:
                prefix = (
                    "لتحديد القطعة من الصورة، اختر المعدة أولًا:"
                    if from_image
                    else "لتحديد القطعة، اختر المعدة أولًا:"
                )
                return self._ask_for_equipment(prefix)
            session = self.store.create(equipment_name)

        if part is not None:
            payload = IdentifyRequest(part_number=part.part_number)
        elif req.image_base64:
            hint = message if self._has_descriptive_text(message) else None
            payload = IdentifyRequest(
                image_base64=req.image_base64,
                transcript=hint,
            )
        elif self._has_descriptive_text(message):
            payload = IdentifyRequest(transcript=message)
        else:
            return ChatResponse(
                message_ar=(
                    "لتحديد القطعة أحتاج صورة واضحة أو رقم القطعة/اسمها. "
                    "فتحت الكاميرا الآن — وجّهها نحو القطعة ثم اضغط «التقاط وتحديد»."
                ),
                source="system",
                action="open_camera",
                session=self._safe_session(session),
                quick_replies=["اعرض القطع", "ما المعدات المتاحة؟"],
            )

        try:
            response = await self.assistant.identify(session.id, payload)
        except SafetyViolation as exc:
            quick = ["ما المعدات المتاحة؟", "اعرض القطع"]
            if part is not None:
                for model in part.equipment_models:
                    quick.insert(0, f"ابدأ جلسة على {model}")
            return ChatResponse(
                message_ar=exc.message_ar,
                source="assistant",
                session=self._safe_session(session),
                quick_replies=quick,
                abstained=True,
                abstention_reason_ar=exc.message_ar,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Unexpected identification failure")
            return self._system_reply(
                "تعذر إكمال التحديد الآن. أعد المحاولة بصورة أوضح أو اختر القطعة يدويًا.",
                session,
            )

        quick = self._session_quick_replies(response)
        action = None
        if response.requires_closer_inspection:
            action = "open_camera"
            quick = ["افتح الكاميرا", "اعرض القطع"] + quick

        return ChatResponse(
            message_ar=response.assistant_message_ar,
            source="assistant",
            action=action,
            session=response,
            quick_replies=quick,
            abstained=response.requires_closer_inspection,
            abstention_reason_ar=response.inspection_prompt_ar,
        )

    # --------------------------------------------------------------- description
    async def _describe(
        self, req: ChatRequest, session: Session | None, message: str
    ) -> ChatResponse:
        if not req.image_base64:
            return self._system_reply(
                "لم تصل صورة لوصفها. افتح الكاميرا والتقط صورة أولًا.", session
            )
        if self.chat is None:
            return self._system_reply(
                "خدمة وصف الصور غير مهيأة على الخادم. يمكنك استخدام أوامر الجلسة "
                "والكاميرا، أو تحديد القطعة من قاعدة المعرفة.",
                session,
            )

        # Image description is deliberately standalone: replaying preceding
        # camera commands biases the model toward troubleshooting instead of
        # describing what is actually visible in the photo.
        reply = await self.chat.reply(
            message=message,
            history=[],
            context=None,
            image_base64=req.image_base64,
            describe=True,
        )
        safe_text = sanitize_user_facing_text(reply.text)
        if reply.error or not safe_text:
            logger.warning(
                "Image description unavailable or rejected: %s",
                reply.error or "unsafe_or_invalid_output",
            )
            return ChatResponse(
                message_ar=(
                    "لم أتمكن من إنشاء وصف موثوق للصورة. لا أستطيع تأكيد هوية القطعة "
                    "من هذا الرد؛ أعد التقاط صورة أو اختر القطعة من قاعدة البيانات."
                ),
                source="system",
                session=self._safe_session(session),
                quick_replies=["حدد القطعة في هذه الصورة", "افتح الكاميرا", "اعرض القطع"],
                abstained=True,
                abstention_reason_ar="تعذر التحقق من مخرجات وصف الصورة.",
            )

        quick = ["حدد القطعة في هذه الصورة", "افتح الكاميرا"]
        if session is not None:
            quick.extend(self._base_quick_replies(session))

        return ChatResponse(
            message_ar=(
                f"{safe_text}\n\n"
                "ملاحظة: هذا وصف عام للصورة وليس تحديدًا معتمدًا. "
                "استخدم «حدد القطعة» للتحقق من قاعدة المعرفة."
            ),
            source="vision",
            quick_replies=quick,
        )

    # ------------------------------------------------------------- manual search
    def _is_manual_search(self, message: str) -> bool:
        normalized = normalize_arabic(message)
        has_manual = any(
            term_in_text(normalized, term)
            for term in ("الكتيبات", "الكتيب", "الدليل", "manual", "manuals")
        )
        has_search = any(
            term_in_text(normalized, term)
            for term in (
                "ابحث", "بحث", "دور", "فتش", "اسال", "جاوب", "سؤال",
                "ما", "ماذا", "كم", "كيف", "اين", "هل", "اشرح", "وضح",
                "what", "which", "how", "where", "when", "why", "explain",
                "describe", "specs", "specification", "search", "find", "ask",
            )
        )
        return has_manual and has_search

    async def _manual_search_reply(
        self, session: Session | None, message: str
    ) -> ChatResponse:
        from app.deps import get_manual_library

        patterns = (
            r"ابحث\s+في\s+الكتيبات?\s+(?:عن|حول)\s+",
            r"ابحث\s+في\s+الدليل\s+(?:عن|حول)\s+",
            r"ابحث\s+بالكتيب\s+(?:عن|حول)\s+",
            r"(?:اسأل|اسال)\s+(?:في\s+)?الكتيبات?\s+(?:عن|حول)\s+",
            r"(?:search|find|ask)\s+(?:in\s+)?manuals?\s+(?:for|about)\s+",
        )
        query = message
        for pattern in patterns:
            query, count = re.subn(pattern, "", query, count=1, flags=re.IGNORECASE)
            if count:
                break
        query = query.strip(" ؟?،,:;")
        if len(query) < 2:
            return self._system_reply(
                "اكتب موضوع السؤال بعد الأمر، مثل: «ابحث في الكتيبات عن مواصفات CPU 1214C».",
                session,
            )

        library = get_manual_library()
        if not library.documents:
            return ChatResponse(
                message_ar=(
                    "لا توجد كتيبات معتمدة مفهرسة حالياً. لم أختلق إجابة صيانة. "
                    "يلزم إتاحة دليل OEM مطابق للمعدة."
                ),
                source="system",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
                abstained=True,
                abstention_reason_ar="دليل OEM غير موجود في فهرس البحث.",
            )

        if session is None:
            return ChatResponse(
                message_ar=(
                    "لا أستطيع اختيار دليل عشوائي للإجابة عن سؤال صيانة. "
                    "التقط صورة للمعدة المدعومة، أكّد هويتها، ثم أعد السؤال."
                ),
                source="system",
                equipment=self.assistant.list_equipment(),
                quick_replies=["افتح الكاميرا"],
                abstained=True,
                abstention_reason_ar="لا توجد معدة مؤكدة لتقييد البحث في دليلها.",
            )

        equipment_model = session.equipment_model
        hits = library.search(query, equipment_model=equipment_model, limit=5)
        if not hits:
            return ChatResponse(
                message_ar=(
                    "لم أجد دليلاً معتمداً مطابقاً للمعدة أو مقاطع كافية للإجابة. "
                    "لن أستخدم معرفة عامة أو أخمّن خطوات الصيانة. تحقق من موديل المعدة "
                    "أو أرفق الدليل المعتمد للمراجعة."
                ),
                source="system",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
                abstained=True,
                abstention_reason_ar="لم يعثر البحث على أدلة مناسبة في الدليل المطابق.",
            )

        # Synthesize only the equipment-scoped manual evidence. Never expose raw chunks.
        if self.chat is None:
            return self._manual_answer_abstention(
                session, "خدمة صياغة الإجابة غير متاحة حالياً."
            )

        manual_context = self._manual_rag_context(hits)
        try:
            reply = await self.chat.reply(
                message=query,
                history=[],
                context=self._context(session),
                manual_context=manual_context,
            )
        except Exception:
            logger.exception("Manual RAG generation failed")
            return self._manual_answer_abstention(
                session, "حدث عطل أثناء صياغة الإجابة من الدليل."
            )

        safe_text = sanitize_user_facing_text(reply.text)
        if safe_text:
            # Only permit citations for source IDs actually present in this response.
            safe_text = re.sub(
                r"\[S(\d+)\]",
                lambda match: match.group(0)
                if 1 <= int(match.group(1)) <= len(hits)
                else "",
                safe_text,
            )
        if safe_text and not re.search(r"\[S[1-5]\]", safe_text):
            safe_text = None
        if safe_text and not self._manual_answer_numbers_are_grounded(safe_text, query, hits):
            logger.warning("Manual RAG answer rejected because it contains unsupported numeric claims")
            safe_text = None

        if reply.error or not safe_text:
            logger.warning(
                "Manual RAG answer unavailable or rejected: %s",
                reply.error or "unsafe_or_invalid_output",
            )
            return self._manual_answer_abstention(
                session, "لم أتمكن من التحقق من إجابة مستندة إلى المقاطع المسترجعة."
            )

        sources = self._manual_source_lines(hits)
        return ChatResponse(
            message_ar=(
                f"{safe_text}\n\nالمراجع المسترجعة:\n{sources}\n\n"
                "هذه إجابة بحثية مرتبطة بنص الكتيب وليست اعتماداً فنياً للتنفيذ. "
                "طابق رقم الطراز ولوحة البيانات ومراجعة الدليل، واطلب مراجعة مختص قبل "
                "أي عمل ميداني. لا تعتمد على الإجابة وحدها لقيم العزم أو إجراءات العزل."
            ),
            source="assistant",
            session=self._safe_session(session),
            quick_replies=["اسأل سؤال صيانة آخر", "افتح الكاميرا"],
        )

    def _manual_answer_abstention(self, session: Session, reason: str) -> ChatResponse:
        return ChatResponse(
            message_ar=(
                "لم أقدم تعليمات صيانة لأن الإجابة لم تجتز التحقق من الدليل. "
                f"{reason} أعد صياغة السؤال أو اطلب مراجعة الدليل من مختص."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=["أعد صياغة السؤال", "افتح الكاميرا"],
            abstained=True,
            abstention_reason_ar=reason,
        )

    def _manual_answer_numbers_are_grounded(self, answer: str, query: str, hits) -> bool:
        """Reject generated numeric claims absent from the question and cited evidence."""
        answer_without_citations = re.sub(r"\[S\d+\]", " ", answer)
        source_parts = [query]
        for index, hit in enumerate(hits, start=1):
            source_parts.extend(
                [
                    hit.excerpt,
                    hit.document_number or "",
                    hit.revision or "",
                    hit.title or "",
                    hit.section_title or "",
                    str(hit.pdf_page_number),
                    str(hit.printed_page_number or ""),
                    str(index),
                ]
            )
        allowed_numbers = set(
            re.findall(r"\d+(?:[.,]\d+)?", normalize_arabic(" ".join(source_parts)))
        )
        answer_numbers = set(
            re.findall(r"\d+(?:[.,]\d+)?", normalize_arabic(answer_without_citations))
        )
        return answer_numbers.issubset(allowed_numbers)

    def _manual_rag_context(self, hits) -> str:
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            page = (
                f"printed page {hit.printed_page_number}; PDF page {hit.pdf_page_number}"
                if hit.printed_page_number
                else f"PDF page {hit.pdf_page_number}"
            )
            document_ref = hit.document_number or hit.document_id
            revision = f"; revision {hit.revision}" if hit.revision else ""
            section = f"; section {hit.section_title}" if hit.section_title else ""
            blocks.append(
                f"[S{index}] OEM: {hit.manufacturer}; title: {hit.title}; "
                f"document: {document_ref}{revision}; {page}{section}\n"
                f"UNTRUSTED EXCERPT:\n{hit.excerpt}"
            )
        return "\n\n".join(blocks)

    def _manual_source_lines(self, hits) -> str:
        lines: list[str] = []
        for index, hit in enumerate(hits, start=1):
            page = (
                f"الصفحة المطبوعة {hit.printed_page_number} (PDF {hit.pdf_page_number})"
                if hit.printed_page_number
                else f"صفحة PDF {hit.pdf_page_number}"
            )
            document_ref = hit.document_number or hit.document_id
            revision = f" — الإصدار: {hit.revision}" if hit.revision else ""
            section = f" — القسم: {hit.section_title}" if hit.section_title else ""
            lines.append(
                f"[S{index}] {hit.manufacturer} — {hit.title}{revision} — "
                f"الوثيقة: {document_ref} — {page}{section}"
            )
            if hit.source_url:
                lines.append(f"رابط المصدر: {hit.source_url}")
        return "\n".join(lines)

    # ----------------------------------------------------------------- grounded
    def _grounded_reply(self, session: Session | None, message: str) -> ChatResponse:
        if session is None:
            return ChatResponse(
                message_ar=(
                    "لا أقدّم قيم عزم أو خطوات فك أو إجراءات عزل من المحادثة العامة. "
                    "هذه المعلومات تتطلب تحديد المعدة والقطعة والتحقق من الدليل المطابق أولاً. "
                    "اختر صورة المعدة للبدء:"
                ),
                source="system",
                equipment=self.assistant.list_equipment(),
                quick_replies=self._equipment_quick_replies(self.assistant.list_equipment()),
                abstained=True,
                abstention_reason_ar="يجب تحديد المعدة والقطعة قبل إجابة سؤال تشغيلي.",
            )

        try:
            response = self.assistant.ask(session.id, AskRequest(transcript=message))
        except SafetyViolation as exc:
            return ChatResponse(
                message_ar=exc.message_ar,
                source="assistant",
                session=self._safe_session(session),
                quick_replies=self._base_quick_replies(session),
                abstained=True,
                abstention_reason_ar=exc.message_ar,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Grounded assistant failure")
            return self._system_reply(
                "تعذر تنفيذ الطلب على الجلسة الحالية. أعد المحاولة أو ابدأ جلسة جديدة.",
                session,
            )

        return ChatResponse(
            message_ar=response.assistant_message_ar,
            source="assistant",
            session=response,
            quick_replies=self._session_quick_replies(response),
            abstained=response.abstained,
            abstention_reason_ar=response.abstention_reason_ar,
        )

    # ------------------------------------------------------------------ general
    async def _general_reply(
        self, req: ChatRequest, session: Session | None, message: str
    ) -> ChatResponse:
        # General-purpose conversation is intentionally outside the locked MVP.
        # Do not call the LLM for unrelated requests.
        return ChatResponse(
            message_ar=(
                "هذا الطلب خارج نطاق مسبار. أستطيع تحديد المعدات المدعومة من الصور، "
                "والبحث في دليل الصيانة المطابق، أو الامتناع عندما لا تتوفر أدلة كافية."
            ),
            source="system",
            session=self._safe_session(session),
            quick_replies=self._base_quick_replies(session),
            abstained=True,
            abstention_reason_ar="الطلب لا يندرج ضمن ميزات MVP المعتمدة.",
        )

    # ------------------------------------------------------------------ helpers
    def _load_session(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        try:
            return self.store.get(session_id)
        except SessionNotFound:
            return None

    def _safe_session(self, session: Session | None):
        if session is None:
            return None
        try:
            return self.assistant.get_session(session.id)
        except SessionNotFound:
            return None

    def _system_reply(
        self,
        message: str,
        session: Session | None,
        equipment: list[EquipmentSummary] | None = None,
        quick_replies: list[str] | None = None,
    ) -> ChatResponse:
        return ChatResponse(
            message_ar=message,
            source="system",
            session=self._safe_session(session),
            equipment=equipment or [],
            quick_replies=quick_replies or self._base_quick_replies(session),
        )

    def _ask_for_equipment(
        self, prefix: str, *, abstained: bool = False, reason: str | None = None
    ) -> ChatResponse:
        equipment = self.assistant.list_equipment()
        return ChatResponse(
            message_ar=f"{prefix}\n\n{self._equipment_text(equipment)}",
            source="system",
            equipment=equipment,
            quick_replies=self._equipment_quick_replies(equipment),
            abstained=abstained,
            abstention_reason_ar=reason,
        )

    def _equipment_text(self, equipment: list[EquipmentSummary]) -> str:
        lines = [
            f"• {item.equipment_family} — {item.component_count} قطع مسجلة"
            for item in equipment
        ]
        return (
            "المعدات المتاحة في قاعدة المعرفة:\n"
            + "\n".join(lines)
            + "\nاختر معدة بالضغط على الزر أو اكتب اسمها."
        )

    def _equipment_quick_replies(
        self, equipment: list[EquipmentSummary]
    ) -> list[str]:
        return ["افتح الكاميرا لبدء تحديد المعدة"]

    def _base_quick_replies(self, session: Session | None) -> list[str]:
        return ["افتح الكاميرا", "شغّل الميكروفون"]

    def _session_quick_replies(self, response) -> list[str]:
        if response.state == SessionState.PENDING_CONFIRMATION:
            return ["تأكيد المعدة", "إعادة التصوير"]
        return ["اسأل عن الصيانة", "افتح الكاميرا"]

    def _component_summaries(self, equipment_model: str) -> list[ComponentSummary]:
        return [
            ComponentSummary(
                part_number=record.part_number,
                english_name=record.english_name,
                arabic_name=record.arabic_name,
                equipment_models=record.equipment_models,
                verification_status=self.kb.data_status_for(record.part_number),
            )
            for record in self.kb.components_for(equipment_model)
        ]

    def _context(self, session: Session | None) -> str:
        if session is None:
            return "لا توجد جلسة صيانة نشطة."
        lines = [
            f"المعدة: {session.equipment_model}",
            f"حالة الجلسة: {_STATE_AR.get(session.state, session.state.value)}",
        ]
        record = self._record(session)
        if record is not None:
            lines.append(f"القطعة المحددة: {record.arabic_name} ({record.part_number})")
            lines.append(f"الخطوة الحالية: {session.step_index} من {len(record.steps)}")
        else:
            lines.append("لم تُحدد قطعة بعد.")
        lines.append(
            "لا تذكر أي قيمة عزم أو خطوات فك أو إجراءات عزل؛ هذه من اختصاص "
            "محرك قاعدة المعرفة الحتمي."
        )
        return "\n".join(lines)

    def _record(self, session: Session) -> ComponentRecord | None:
        if not session.part_number:
            return None
        return self.kb.get_component(session.part_number)

    # ------------------------------------------------------------- text parsing
    def _find_equipment(self, text: str) -> str | None:
        if not text:
            return None
        normalized = normalize_arabic(text)
        scores: dict[str, int] = {}
        for name in self.kb.equipment_names():
            score = 0
            if normalize_arabic(name) in normalized:
                score += 100
            for alias in _EQUIPMENT_ALIASES.get(name, ()):
                if term_in_text(text, alias):
                    score += max(4, len(normalize_arabic(alias)))
            if score:
                scores[name] = score

        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None
        if ranked[0][1] < 4:
            return None
        return ranked[0][0]

    def _find_part(self, text: str) -> ComponentRecord | None:
        if not text:
            return None
        normalized = normalize_arabic(text)
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        best: ComponentRecord | None = None
        for key, record in self.kb.components.items():
            key_lower = key.lower()
            compact_key = re.sub(r"[^a-z0-9]", "", key_lower)
            if key_lower in normalized or (compact_key and compact_key in compact):
                if best is None or len(key) > len(best.part_number):
                    best = record
        return best

    def _has_descriptive_text(self, message: str) -> bool:
        tokens = [token for token in tokenize(message) if token not in _COMMAND_STOPWORDS]
        # Part numbers survive tokenization as a single token.
        if any(token in {record.part_number.lower() for record in self.kb.components.values()} for token in tokens):
            return True
        return bool(tokens)

    def _tokens(self, text: str) -> set[str]:
        return set(tokenize(text))

    def _is_open_camera(self, message: str) -> bool:
        tokens = self._tokens(message)
        if "كاميرا" in tokens or "كاميره" in tokens:
            return bool(tokens & _OPEN_CAMERA_VERBS)
        if "التقط" in tokens:
            return True
        return "خذ" in tokens and bool({"صوره", "صور"} & tokens)

    def _is_close_camera(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(tokens & _CLOSE_WORDS) and bool({"كاميرا", "كاميره"} & tokens)

    def _is_start_listening(self, message: str) -> bool:
        tokens = self._tokens(message)
        if tokens & {"ميكروفون", "مايك"}:
            return bool(tokens & {"شغل", "فتح", "افتح", "ابدأ", "استمع", "اسمع"})
        return bool(tokens & {"استمع", "اسمعني"}) and "اوقف" not in tokens

    def _is_stop_listening(self, message: str) -> bool:
        tokens = self._tokens(message)
        if tokens & {"ميكروفون", "مايك"}:
            return bool(tokens & _STOP_MIC_WORDS)
        return bool(tokens & {"اسكت", "كفى"}) or (
            "توقف" in tokens and bool(tokens & {"استماع", "استمع"})
        )

    def _is_equipment_list(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(tokens & {"معدات", "اجهزه", "الات"})

    def _is_manufacturer_list(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(
            tokens
            & {
                "شركات",
                "شركه",
                "مصنعين",
                "مصنعون",
                "مصنّعين",
                "علامات",
                "brands",
                "manufacturers",
                "oem",
            }
        )

    def _is_oem_data_question(self, message: str) -> bool:
        tokens = self._tokens(message)
        has_data_word = bool(tokens & {"بيانات", "مصدر", "مصادر", "كتيب", "كتالوج"})
        has_quality_word = bool(
            tokens & {"حقيقيه", "حقيقية", "رسمي", "رسمية", "موثوق", "موثوقه", "موثوقة", "oem"}
        )
        oem_terms = ("oem", "بيانات حقيقيه", "بيانات حقيقية", "دليل الخدمه", "دليل الخدمة")
        return (has_data_word and has_quality_word) or any(
            term_in_text(message, term) for term in oem_terms
        )

    def _is_component_list(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(tokens & {"قطع", "غيار"}) and not bool(tokens & {"قطعه"})

    def _is_start_session(self, message: str) -> bool:
        tokens = self._tokens(message)
        if "جلسه" not in tokens and "جلسات" not in tokens:
            return False
        return bool(tokens & {"ابدا", "بدء", "جديده", "جديد", "افتح", "start"})

    def _wants_identify(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(tokens & {"حدد", "تحديد", "تعرف", "اعرف"})

    def _is_help(self, message: str) -> bool:
        tokens = self._tokens(message)
        return bool(tokens & {"مساعده", "help", "مساعدتك"}) or any(
            term_in_text(message, term) for term in _HELP_TERMS
        )

    def _is_maintenance_query(self, message: str) -> bool:
        terms = (
            "hydraulic", "oil", "fluid", "filter", "level", "leak", "maintenance",
            "service", "fault", "failure", "symptom", "diagnosis", "diagnostic",
            "repair", "troubleshoot", "pump", "pressure", "coolant", "lubrication",
            "هيدروليك", "زيت", "زيوت", "سائل", "فلتر", "مستوى", "تهريب",
            "تسريب", "صيانة", "عطل", "خلل", "تشخيص", "اصلاح", "مضخه",
            "ضغط", "تبريد", "شحوم", "تزييت",
        )
        return any(term_in_text(message, term) for term in terms)

    def _needs_grounded_answer(self, message: str) -> bool:
        return any(term_in_text(message, term) for term in _GROUNDED_TERMS)
