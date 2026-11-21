from app.core.arabic import normalize_arabic, term_in_text, tokenize
from app.domain.enums import Intent
from app.knowledge.lexicon import expand_query, extract_concepts


def test_arabic_article_prefix_is_matched():
    # The original implementation used \b and missed "البلف" entirely.
    assert term_in_text("البلف يهرب ديزل", "بلف")
    assert term_in_text("الصمام يسرب زيت", "صمام")
    assert term_in_text("الطرمبة فيها ضعف", "طرمبة")


def test_short_arabic_terms_do_not_match_inside_other_words():
    assert not term_in_text("الخطوة التالية", "لي")
    assert term_in_text("لي", "لي")
    assert term_in_text("افحص الخرطوم", "خرطوم")


def test_normalization_handles_diacritics_and_digits():
    assert normalize_arabic("٣١٢-٥٦٢٠") == "312-5620"
    assert normalize_arabic("الصّمّام") == normalize_arabic("الصمام")
    assert normalize_arabic("أعِد") == "اعد"


def test_intents_detect_real_field_phrases():
    assert expand_query("كم عزم الشد حقته؟").intent == Intent.TORQUE_QUERY
    assert expand_query("الخطوة التالية").intent == Intent.NEXT_STEP
    assert expand_query("تم العزل أكمل").intent == Intent.CONFIRM_LOTO
    assert expand_query("ما رقم القطعة؟").intent == Intent.PART_NUMBER_QUERY
    assert expand_query("أعد الخطوة").intent == Intent.REPEAT_STEP


def test_dialect_concepts_are_expanded():
    concepts = {concept.key for concept in extract_concepts("البلف يهرب ديزل والطرمبة ضعيفة")}
    assert "valve" in concepts
    assert "leak" in concepts
    assert "pump" in concepts


def test_tokenizer_strips_articles_and_stopwords():
    tokens = tokenize("هذا الصمام في الطرمبة")
    assert "صمام" in tokens
    assert "طرمبه" in tokens
    assert "هذا" not in tokens
