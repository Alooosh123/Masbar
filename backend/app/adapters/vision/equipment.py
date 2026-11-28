from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class EquipmentVisionResult:
    equipment_model: str | None
    confidence: float
    provider: str
    error: str | None = None


SYSTEM_PROMPT = """أنت مصنف بصري للمعدات الصناعية.
حدد نوع المعدة الظاهرة في الصورة من القائمة المغلقة التي يرسلها النظام فقط.
لا تستخدم أسماء أو طرازات من خارج القائمة.
إذا كانت الصورة غير واضحة أو لا تطابق أي عنصر، أعد equipment_model كسلسلة فارغة وconfidence=0.
لا تستنتج هوية المعدة من نص المستخدم؛ اعتمد على الصورة.
أعد JSON مطابقاً للمخطط فقط."""


class EquipmentVisionAdapter:
    """Classify equipment from an image against the application's closed equipment catalog."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_image_bytes: int = 8 * 1024 * 1024,
    ):
        self.provider = provider.strip().lower()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes

    def _decode_image(self, image_base64: str) -> tuple[str, str] | None:
        value = image_base64.strip()
        mime_type = "image/jpeg"
        encoded = value
        if value.startswith("data:"):
            header, separator, encoded = value.partition(",")
            if not separator:
                return None
            match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64", header, re.IGNORECASE)
            if not match:
                return None
            mime_type = match.group(1).lower()
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        if not raw or len(raw) > self.max_image_bytes:
            return None
        return mime_type, base64.b64encode(raw).decode("ascii")

    async def identify(
        self, image_base64: str | None, equipment_models: list[str]
    ) -> EquipmentVisionResult:
        provider_label = f"{self.provider}:{self.model}"
        if not image_base64:
            return EquipmentVisionResult(None, 0.0, provider_label, "image_required")
        decoded = self._decode_image(image_base64)
        if decoded is None:
            return EquipmentVisionResult(None, 0.0, provider_label, "invalid_or_oversized_image")
        allowed = [name for name in equipment_models if name]
        if not allowed:
            return EquipmentVisionResult(None, 0.0, provider_label, "empty_equipment_catalog")

        mime_type, encoded = decoded
        image_url = f"data:{mime_type};base64,{encoded}"
        schema = {
            "type": "object",
            "properties": {
                "equipment_model": {"type": "string", "enum": allowed + [""]},
                "confidence": {"type": "number"},
            },
            "required": ["equipment_model", "confidence"],
            "additionalProperties": False,
        }
        user_text = (
            "قائمة المعدات المدعومة:\n"
            + "\n".join(f"- {name}" for name in allowed)
            + "\nحدد المعدة الظاهرة في الصورة فقط."
        )
        if self.provider == "cohere":
            endpoint = f"{self.base_url}/chat"
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
                "response_format": {"type": "json_object", "schema": schema},
            }
        elif self.provider in {"openai", "openrouter"}:
            endpoint = f"{self.base_url}/chat/completions"
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
        else:
            return EquipmentVisionResult(None, 0.0, provider_label, "unsupported_vision_provider")

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            return EquipmentVisionResult(None, 0.0, provider_label, "vision_timeout")
        except httpx.HTTPStatusError as exc:
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
            return EquipmentVisionResult(None, 0.0, provider_label, error)
        except httpx.RequestError:
            return EquipmentVisionResult(None, 0.0, provider_label, "vision_network_error")
        except Exception:
            return EquipmentVisionResult(None, 0.0, provider_label, "vision_provider_error")

        try:
            if self.provider == "cohere":
                parts = data.get("message", {}).get("content", [])
                content = "".join(
                    item.get("text", "")
                    for item in parts
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            else:
                content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return EquipmentVisionResult(None, 0.0, provider_label, "invalid_provider_response")
            raw_model = parsed.get("equipment_model")
            raw_confidence = parsed.get("confidence")
            if not isinstance(raw_model, str):
                return EquipmentVisionResult(None, 0.0, provider_label, "invalid_provider_response")
            if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
                return EquipmentVisionResult(None, 0.0, provider_label, "invalid_confidence")
            equipment_model = raw_model.strip()
            confidence = float(raw_confidence)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return EquipmentVisionResult(None, 0.0, provider_label, "invalid_provider_response")

        if not 0.0 <= confidence <= 1.0:
            return EquipmentVisionResult(None, 0.0, provider_label, "invalid_confidence")
        if not equipment_model:
            return EquipmentVisionResult(None, confidence, provider_label, "unclear_image")
        if equipment_model not in allowed:
            return EquipmentVisionResult(None, confidence, provider_label, "unsupported_equipment_result")
        return EquipmentVisionResult(equipment_model, confidence, provider_label)
