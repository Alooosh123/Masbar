from __future__ import annotations

import json
import re

import httpx

from app.adapters.vision.base import VisionResult, clamp_box
from app.knowledge.loader import KnowledgeBase

SYSTEM_PROMPT = """أنت محدد قطع غيار صناعي. مهمتك اختيار القطعة المطابقة من قائمة مرشحين فقط.
قواعد صارمة:
1. لا تخترع أي رقم قطعة غير موجود في القائمة.
2. إذا لم تكن القطعة واضحة أو لم تجد مطابقة، أعد part_number كسلسلة فارغة وconfidence = 0.
3. أعد كائن JSON واحدًا فقط يطابق المخطط، ولا تعد المخطط نفسه.
4. bounding_box إحداثيات نسبية من 0 إلى 1 بالشكل [x1, y1, x2, y2]، أو [] عند عدم اليقين.
5. label وصف قصير للقطعة، أو سلسلة فارغة عند عدم اليقين."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "part_number": {
            "type": "string",
            "description": "Exact part number from the candidate list, or an empty string.",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence between 0 and 1.",
        },
        "bounding_box": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Normalized x1,y1,x2,y2 coordinates, or an empty array.",
        },
        "label": {
            "type": "string",
            "description": "Short part label, or an empty string.",
        },
    },
    "required": ["part_number", "confidence", "bounding_box", "label"],
    "additionalProperties": False,
}


class CohereVisionAdapter:
    """Grounded VLM classification through Cohere Chat v2 structured outputs."""

    def __init__(
        self,
        kb: KnowledgeBase,
        api_key: str,
        base_url: str = "https://api.cohere.com/v2",
        model: str = "command-a-vision-07-2025",
        timeout_seconds: float = 30.0,
    ):
        self.kb = kb
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def identify(
        self,
        image_base64: str | None,
        equipment_model: str,
        hint: str | None = None,
    ) -> VisionResult:
        if not image_base64:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"cohere:{self.model}",
                error="image_required",
            )

        candidates = self.kb.components_for(equipment_model)
        if not candidates:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"cohere:{self.model}",
                error="no_components_for_equipment",
            )

        candidate_lines = "\n".join(
            f"- {c.part_number} | {c.english_name} | {c.arabic_name}" for c in candidates
        )
        user_text = (
            f"المعدة: {equipment_model}\n"
            f"ملاحظة الفني: {hint or 'لا يوجد'}\n"
            f"قائمة المرشحين:\n{candidate_lines}\n"
            "اختر القطعة الظاهرة في الصورة. لا تخترع رقمًا خارج القائمة."
        )

        image_url = image_base64
        if not image_url.startswith("data:"):
            image_url = f"data:image/jpeg;base64,{image_url}"

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "response_format": {"type": "json_object", "schema": RESPONSE_SCHEMA},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # pragma: no cover - network dependent
            error = f"vision_provider_error: {type(exc).__name__}"
            if isinstance(exc, httpx.HTTPStatusError):
                error = f"vision_provider_error: http_{exc.response.status_code}"
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"cohere:{self.model}",
                error=error,
            )

        try:
            content = _extract_text(data)
            parsed = json.loads(_strip_code_fences(content))
        except Exception:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"cohere:{self.model}",
                error="invalid_provider_json",
            )

        part_number = str(parsed.get("part_number") or "").strip()
        if not part_number:
            return VisionResult(
                part_number=None,
                confidence=_safe_confidence(parsed.get("confidence")),
                provider=f"cohere:{self.model}",
                error="no_match",
            )

        allowed = {c.part_number.upper() for c in candidates}
        if part_number.upper() not in allowed:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"cohere:{self.model}",
                error="part_number_not_in_candidates",
            )

        label = parsed.get("label")
        return VisionResult(
            part_number=part_number.upper(),
            confidence=_safe_confidence(parsed.get("confidence")),
            bounding_box=clamp_box(parsed.get("bounding_box")),
            label=label.strip() if isinstance(label, str) and label.strip() else None,
            provider=f"cohere:{self.model}",
        )


def _extract_text(data: dict) -> str:
    content = data.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(parts)
    return ""


def _safe_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _strip_code_fences(content: str) -> str:
    if not isinstance(content, str):
        return "{}"
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, flags=re.DOTALL)
    if match:
        return match.group(1)
    return content.strip()
