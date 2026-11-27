from __future__ import annotations

from app.adapters.vision.cohere_vlm import CohereVisionAdapter
from app.adapters.vision.equipment import EquipmentVisionAdapter
from app.adapters.vision.mock import MockVisionAdapter
from app.adapters.vision.openai_vlm import OpenAIVisionAdapter
from app.core.config import Settings
from app.knowledge.loader import KnowledgeBase

DEFAULT_VISION_MODELS = {
    "openai": "gpt-4o-mini",
    "cohere": "command-a-vision-07-2025",
}


def build_vision_adapter(kb: KnowledgeBase, settings: Settings):
    provider = settings.vision_provider.strip().lower()

    if provider == "mock":
        return MockVisionAdapter(kb)

    if provider not in DEFAULT_VISION_MODELS:
        raise RuntimeError(
            f"Unsupported VISION_PROVIDER={settings.vision_provider!r}. "
            "Use mock, openai, or cohere."
        )

    model = settings.vision_model or DEFAULT_VISION_MODELS[provider]

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "VISION_PROVIDER=openai but OPENAI_API_KEY is not set. "
                "Add the key to .env or set VISION_PROVIDER=mock."
            )
        return OpenAIVisionAdapter(
            kb=kb,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=model,
            timeout_seconds=settings.vision_timeout_seconds,
        )

    if provider == "cohere":
        if not settings.cohere_api_key:
            raise RuntimeError(
                "VISION_PROVIDER=cohere but COHERE_API_KEY is not set. "
                "Add the key to .env or set VISION_PROVIDER=mock."
            )
        return CohereVisionAdapter(
            kb=kb,
            api_key=settings.cohere_api_key,
            base_url=settings.cohere_base_url,
            model=model,
            timeout_seconds=settings.vision_timeout_seconds,
        )

    raise RuntimeError(
        f"Unsupported VISION_PROVIDER={settings.vision_provider!r}. "
        "Use mock, openai, or cohere."
    )



def build_equipment_vision_adapter(settings: Settings) -> EquipmentVisionAdapter | None:
    """Build real equipment-level vision; mock providers are deliberately unavailable."""
    provider = settings.vision_provider.strip().lower()
    if provider == "mock":
        return None

    if provider == "cohere":
        if not settings.cohere_api_key:
            raise RuntimeError("COHERE_API_KEY is required for equipment image identification.")
        return EquipmentVisionAdapter(
            provider=provider,
            api_key=settings.cohere_api_key,
            base_url=settings.cohere_base_url,
            model=settings.vision_model or DEFAULT_VISION_MODELS["cohere"],
            timeout_seconds=settings.vision_timeout_seconds,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for equipment image identification.")
        return EquipmentVisionAdapter(
            provider=provider,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.vision_model or DEFAULT_VISION_MODELS["openai"],
            timeout_seconds=settings.vision_timeout_seconds,
        )

    raise RuntimeError(f"Unsupported VISION_PROVIDER={settings.vision_provider!r}.")
