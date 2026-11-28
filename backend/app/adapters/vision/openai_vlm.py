from __future__ import annotations

import json
import logging
import re

import httpx

from app.adapters.vision.base import VisionResult, clamp_box
from app.knowledge.loader import KnowledgeBase

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """أنت محدد قطع غيار صناعي. مهمتك اختيار القطعة المطابقة من قائمة مرشحين فقط.
قواعد صارمة:
1. لا تخترع أي رقم قطعة غير موجود في القائمة.
2. إذا لم تكن القطعة واضحة أو لم تجد مطابقة، أعد part_number = null.
3. أعد JSON فقط دون أي نص إضافي بالشكل:
{"part_number": "..." أو null, "confidence": 0.0-1.0, "bounding_box": [x1,y1,x2,y2], "label": "..."}
حيث bounding_box إحداثيات نسبية من 0 إلى 1."""


class OpenAIVisionAdapter:
    """Grounded VLM classification against a closed candidate list."""

    def __init__(
        self,
        kb: KnowledgeBase,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
        provider_name: str = "openai",
    ):
        self.kb = kb
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.provider_name = provider_name

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
                provider=f"{self.provider_name}:{self.model}",
                error="image_required",
            )

        candidates = self.kb.components_for(equipment_model)
        if not candidates:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"{self.provider_name}:{self.model}",
                error="no_components_for_equipment",
            )

        candidate_lines = "\n".join(
            f"- {c.part_number} | {c.english_name} | {c.arabic_name}" for c in candidates
        )
        user_text = (
            f"المعدة: {equipment_model}\n"
            f"ملاحظة الفني: {hint or 'لا يوجد'}\n"
            f"قائمة المرشحين:\n{candidate_lines}\n"
            "اختر القطعة الظاهرة في الصورة."
        )

        image_url = image_base64
        if not image_url.startswith("data:"):
            image_url = f"data:image/jpeg;base64,{image_base64}"

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
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
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:  # pragma: no cover - network dependent
            logger.warning("vision request timeout provider=%s model=%s", self.provider_name, self.model)
            return VisionResult(None, 0.0, f"{self.provider_name}:{self.model}", error="vision_timeout")
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network dependent
            status_code = exc.response.status_code
            if status_code in {402, 403}:
                error = "vision_payment_or_quota_required"
            elif status_code == 401:
                error = "vision_api_key_invalid"
            elif status_code == 429:
                error = "vision_rate_limited"
            elif status_code >= 500:
                error = "vision_provider_unavailable"
            else:
                error = "vision_provider_rejected_request"
            logger.warning("vision provider rejected request provider=%s model=%s status=%s code=%s", self.provider_name, self.model, status_code, error)
            return VisionResult(None, 0.0, f"{self.provider_name}:{self.model}", error=error)
        except httpx.RequestError:  # pragma: no cover - network dependent
            logger.warning("vision network failure provider=%s model=%s", self.provider_name, self.model)
            return VisionResult(None, 0.0, f"{self.provider_name}:{self.model}", error="vision_network_error")

        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_code_fences(content))
        except Exception:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"{self.provider_name}:{self.model}",
                error="invalid_provider_json",
            )

        part_number = parsed.get("part_number")
        if part_number is None:
            return VisionResult(
                part_number=None,
                confidence=float(parsed.get("confidence") or 0.0),
                provider=f"{self.provider_name}:{self.model}",
                error="no_match",
            )

        allowed = {c.part_number.upper() for c in candidates}
        if str(part_number).strip().upper() not in allowed:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider=f"{self.provider_name}:{self.model}",
                error="part_number_not_in_candidates",
            )

        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0

        return VisionResult(
            part_number=str(part_number).strip().upper(),
            confidence=confidence,
            bounding_box=clamp_box(parsed.get("bounding_box")),
            label=parsed.get("label"),
            provider=f"{self.provider_name}:{self.model}",
        )


def _strip_code_fences(content: str) -> str:
    if not isinstance(content, str):
        return "{}"
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, flags=re.DOTALL)
    if match:
        return match.group(1)
    return content.strip()
