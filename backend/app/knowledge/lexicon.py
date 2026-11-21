"""
Arabic ↔ English industrial lexicon.

Maps dialect and workshop vocabulary (Gulf, Egyptian, Levantine) to canonical
engineering concepts used by the English maintenance manuals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.arabic import normalize_arabic, term_in_text
from app.domain.enums import Intent


@dataclass(frozen=True)
class Concept:
    key: str
    canonical_en: str
    canonical_ar: str
    aliases: tuple[str, ...]


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        key="valve",
        canonical_en="valve",
        canonical_ar="صمام",
        aliases=("بلف", "بلوف", "صمام", "صمامات", "فالف", "فالفات", "valve"),
    ),
    Concept(
        key="solenoid_valve",
        canonical_en="solenoid valve",
        canonical_ar="صمام ملف لولبي",
        aliases=("سولونويد", "سلونويد", "solenoid", "صمام كهربائي"),
    ),
    Concept(
        key="pump",
        canonical_en="pump",
        canonical_ar="مضخة",
        aliases=("طرمبه", "طرمبة", "مضخه", "مضخة", "بومبه", "بومبة", "pump"),
    ),
    Concept(
        key="sensor",
        canonical_en="sensor",
        canonical_ar="حساس",
        aliases=("حساس", "حساسات", "سنسور", "سينسور", "sensor", "transducer"),
    ),
    Concept(
        key="relay",
        canonical_en="relay",
        canonical_ar="مرحل",
        aliases=("كتاوت", "كتاوتات", "ريليه", "رليه", "ريلاي", "relay", "contactor", "كونتاكتور"),
    ),
    Concept(
        key="gasket",
        canonical_en="gasket",
        canonical_ar="حشية",
        aliases=("وجيه", "وجيهات", "كازكيت", "قازقيت", "حشيه", "حشية", "gasket"),
    ),
    Concept(
        key="seal",
        canonical_en="oil seal",
        canonical_ar="مانع تسرب",
        aliases=("صوفه", "صوفة", "سيل", "سيلز", "مانع تسرب", "o-ring", "اورينق", "oil seal", "seal"),
    ),
    Concept(
        key="hose",
        canonical_en="hose",
        canonical_ar="خرطوم",
        aliases=("لي", "خرطوم", "خراطيم", "هوز", "hose"),
    ),
    Concept(
        key="filter",
        canonical_en="filter",
        canonical_ar="فلتر",
        aliases=("فلتر", "فلاتر", "مصفي", "مصفاة", "filter"),
    ),
    Concept(
        key="injector",
        canonical_en="fuel injector",
        canonical_ar="حاقن وقود",
        aliases=("بخاخ", "بخاخات", "انجكتر", "انجكتور", "حاقن", "injector"),
    ),
    Concept(
        key="turbo",
        canonical_en="turbocharger",
        canonical_ar="شاحن توربيني",
        aliases=("تيربو", "توربو", "شاحن", "turbo", "turbocharger"),
    ),
    Concept(
        key="alternator",
        canonical_en="alternator",
        canonical_ar="مولد كهربائي",
        aliases=("دينمو", "دينامو", "مولد", "alternator"),
    ),
    Concept(
        key="starter",
        canonical_en="starter motor",
        canonical_ar="مارش",
        aliases=("سلف", "مارش", "starter"),
    ),
    Concept(
        key="torque",
        canonical_en="torque specification",
        canonical_ar="عزم شد",
        aliases=("عزم", "شد", "ربطه", "ربطة", "نيوتن", "torque", "nm", "n m"),
    ),
    Concept(
        key="leak",
        canonical_en="leakage",
        canonical_ar="تسريب",
        aliases=("يسرب", "يهرب", "تسريب", "تهريب", "ينقط", "نقط", "leak", "leakage"),
    ),
    Concept(
        key="battery",
        canonical_en="battery",
        canonical_ar="بطارية",
        aliases=("بطاريه", "بطارية", "battery"),
    ),
    Concept(
        key="pressure",
        canonical_en="pressure",
        canonical_ar="ضغط",
        aliases=("ضغط", "بريشر", "pressure"),
    ),
    Concept(
        key="connector",
        canonical_en="electrical connector",
        canonical_ar="فيش كهربائي",
        aliases=("فيش", "فیش", "قابس", "كونكتر", "connector", "plug"),
    ),
    Concept(
        key="wiring",
        canonical_en="wiring",
        canonical_ar="توصيلات كهربائية",
        aliases=("سلك", "اسلاك", "أسلاك", "كهرباء", "wiring", "wire"),
    ),
    Concept(
        key="bolt",
        canonical_en="bolt",
        canonical_ar="مسمار",
        aliases=("مسمار", "مسامير", "برغي", "bolt"),
    ),
    Concept(
        key="contactor",
        canonical_en="contactor",
        canonical_ar="كونتاكتور",
        aliases=("كونتاكتور", "كونتاكتور", "contactor"),
    ),
)


@dataclass
class ExpandedQuery:
    raw: str
    normalized: str
    intent: Intent
    concepts: list[Concept] = field(default_factory=list)
    english_terms: list[str] = field(default_factory=list)
    arabic_terms: list[str] = field(default_factory=list)

    @property
    def search_terms(self) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []
        for term in [*self.english_terms, *self.arabic_terms]:
            key = normalize_arabic(term)
            if key and key not in seen:
                seen.add(key)
                terms.append(term)
        return terms


_INTENT_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        Intent.TORQUE_QUERY,
        ("عزم", "شد", "نيوتن", "torque", "كم اربط", "كم اشد", "قوه الشد"),
    ),
    (
        Intent.PART_NUMBER_QUERY,
        ("رقم القطعه", "رقم القطعة", "رقمه", "بارت", "part number", "سيريال", "رقم الصمام", "رقم المضخه"),
    ),
    (
        Intent.CONFIRM_LOTO,
        ("فصلت", "تم العزل", "تم فصل", "اكمل", "أكمل", "مفصول", "loto", "عزلت"),
    ),
    (
        Intent.NEXT_STEP,
        ("اللي بعده", "اللي بعدها", "التالي", "التاليه", "خلصت", "تمام", "نكمل", "كمل", "next"),
    ),
    (
        Intent.REPEAT_STEP,
        ("اعد", "أعد", "كرر", "عيد", "ما سمعت", "وضح اكثر", "repeat"),
    ),
    (
        Intent.PREV_STEP,
        ("السابق", "ارجع", "رجع", "الخطوه اللي قبل", "previous", "back"),
    ),
    (
        Intent.SAFETY_QUERY,
        ("خطر", "تحذير", "سلامه", "سلامة", "امن", "آمن", "عزل", "قفل", "safety"),
    ),
    (
        Intent.HELP,
        ("مساعده", "مساعدة", "ساعدني", "الاوامر", "الأوامر", "شو اقدر", "كيف استخدم"),
    ),
    (
        Intent.IDENTIFY,
        ("هذا", "هذه", "حدد", "شوف", "القطعه", "القطعة", "وش هذا", "ايش هذا", "شنو هذا"),
    ),
)


def detect_intent(text: str) -> Intent:
    for intent, phrases in _INTENT_RULES:
        if any(term_in_text(text, phrase) for phrase in phrases):
            return intent
    return Intent.UNKNOWN


def extract_concepts(text: str) -> list[Concept]:
    return [concept for concept in CONCEPTS if any(term_in_text(text, alias) for alias in concept.aliases)]


def expand_query(text: str) -> ExpandedQuery:
    concepts = extract_concepts(text)
    english_terms = [concept.canonical_en for concept in concepts]
    arabic_terms = [concept.canonical_ar for concept in concepts]
    return ExpandedQuery(
        raw=text,
        normalized=normalize_arabic(text),
        intent=detect_intent(text),
        concepts=concepts,
        english_terms=english_terms,
        arabic_terms=arabic_terms,
    )
