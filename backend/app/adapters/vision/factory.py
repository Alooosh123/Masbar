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
    "openrouter": "qwen/qwen3-vl-8b-instruct",
}


def build_vision_adapter(kb: KnowledgeBase, settings: Settings):
    provider = settings.vision_provider.strip().lower()

    if provider == "mock":
        return MockVisionAdapter(kb)

    if provider not in DEFAULT_VISION_MODELS:
        raise RuntimeError(
            f"Unsupported VISION_PROVIDER={settings.vision_provider!r}. "
            "Use mock, openai, cohere, or openrouter."
        )

    model = settings.vision_model or DEFAULT_VISION_MODELS[provider]

    if provider in {"openai", "openrouter"}:
        api_key = (
            settings.openrouter_api_key
            if provider == "openrouter"
            else settings.openai_api_key
        )
        base_url = (
            settings.openrouter_base_url
            if provider == "openrouter"
            else settings.openai_base_url
        )
        key_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        if not api_key:
            raise RuntimeError(
                f"VISION_PROVIDER={provider} but {key_name} is not set. "
                "Add the key to the backend environment or choose another provider."
            )
        return OpenAIVisionAdapter(
            kb=kb,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=settings.vision_timeout_seconds,
            provider_name=provider,
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

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for equipment image identification.")
        return EquipmentVisionAdapter(
            provider=provider,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=settings.vision_model or DEFAULT_VISION_MODELS["openrouter"],
            timeout_seconds=settings.vision_timeout_seconds,
        )

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

    raise RuntimeError(
        f"Unsupported VISION_PROVIDER={settings.vision_provider!r}. "
        "Use mock, openai, cohere, or openrouter."
    )
