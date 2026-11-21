"""
Arabic text normalization tuned for industrial field speech.

The original starter used `\\b` word boundaries, which silently fails on the
most common Arabic form: the definite article "ال" glued to the noun
("البلف", "الصمام", "الطرمبة"). This module normalizes orthography first and
then performs boundary-aware matching for both Arabic and Latin scripts.
"""

from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_NON_WORD = re.compile(r"[^\w\s\-]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_ARABIC_STOPWORDS = {
    "هذا",
    "هذه",
    "هاذا",
    "هاذي",
    "ذا",
    "ذي",
    "من",
    "في",
    "على",
    "عن",
    "الى",
    "إلى",
    "ما",
    "ماذا",
    "كيف",
    "هل",
    "يا",
    "مع",
    "ثم",
    "او",
    "أو",
    "ان",
    "أن",
    "كان",
    "هو",
    "هي",
    "كم",
    "لي",
    "لو",
    "و",
    "ال",
    "هنا",
    "هناك",
}


def normalize_arabic(text: str) -> str:
    """Return a comparison-safe representation of Arabic/Latin mixed text."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _DIACRITICS.sub("", text)
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    text = text.translate(_ARABIC_INDIC)
    text = text.lower()
    text = _NON_WORD.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def strip_article(token: str) -> str:
    """Strip the Arabic definite article when it is a real prefix, not the word itself."""
    if len(token) > 4 and token.startswith("ال"):
        return token[2:]
    return token


def tokenize(text: str) -> list[str]:
    normalized = normalize_arabic(text)
    if not normalized:
        return []
    tokens: list[str] = []
    for token in normalized.split(" "):
        if not token or token in _ARABIC_STOPWORDS:
            continue
        stripped = strip_article(token)
        if stripped and stripped not in _ARABIC_STOPWORDS:
            tokens.append(stripped)
        else:
            tokens.append(token)
    return tokens


def term_in_text(text: str, term: str) -> bool:
    """
    Check for a term inside text after normalization.

    Latin terms use real boundaries so "pump" does not match "pumping" by
    accident; Arabic terms are matched as substrings because prefixes and
    suffixes (ال، و، ها، ي) are routinely attached in dialect speech.
    """
    normalized_text = normalize_arabic(text)
    normalized_term = normalize_arabic(term)
    if not normalized_text or not normalized_term:
        return False

    if re.fullmatch(r"[a-z0-9 \-]+", normalized_term):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None

    # Short Arabic terms ("لي", "شد") must match a whole token, otherwise they
    # explode into false positives inside unrelated words ("التالي", "رشد").
    if " " not in normalized_term and len(normalized_term) <= 3:
        return any(
            token == normalized_term or strip_article(token) == normalized_term
            for token in normalized_text.split()
        )

    return normalized_term in normalized_text
