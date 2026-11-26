from __future__ import annotations

import re

_INTERNAL_OUTPUT_MARKERS = (
    "user asks", "they want", "we should respond", "we should answer",
    "no need to ask for details", "the user wants", "assistant analysis",
    "chain of thought", "internal reasoning", "developer message",
    "system prompt", "scratchpad",
)
_INTERNAL_PREFIX = re.compile(
    r"(?im)^\s*(?:analysis|assistant analysis|developer|system|user asks|we should respond|we should answer)\s*[:>\-]"
)
_INTERNAL_TAG = re.compile(r"<\s*/?\s*(?:analysis|developer|system|scratchpad)\b", re.I)
_TOKEN_ARTIFACT = re.compile(r"<\|(?:im_start|im_end|fim_prefix|fim_middle|fim_suffix|gh[a-z_]+)\|>", re.I)


def sanitize_user_facing_text(value: str | None) -> str | None:
    """Reject malformed or internal-looking model output instead of exposing it."""
    if not isinstance(value, str):
        return None
    text = value.replace("\x00", "").strip()
    if not text or len(text) > 7000:
        return None
    lowered = text.casefold()
    if _INTERNAL_PREFIX.search(text) or _INTERNAL_TAG.search(text) or _TOKEN_ARTIFACT.search(text):
        return None
    if any(marker in lowered for marker in _INTERNAL_OUTPUT_MARKERS):
        return None
    if text.count(chr(96)) >= 3 or "json_schema" in lowered or "response_format" in lowered:
        return None
    if not re.search(r"[\u0600-\u06ffA-Za-z0-9]", text):
        return None
    return text
