from __future__ import annotations

from app.adapters.chat.cohere_chat import CohereChatAdapter
from app.core.config import Settings


def chat_is_configured(settings: Settings) -> bool:
    provider = (settings.chat_provider or "").strip().lower()
    if provider == "cohere":
        return bool(settings.cohere_api_key)
    return False


def build_chat_adapter(settings: Settings) -> CohereChatAdapter | None:
    """Build the general-conversation adapter, or None when it is disabled.

    A missing chat adapter must never disable the deterministic maintenance
    engine; the UI simply falls back to command-only conversation.
    """

    provider = (settings.chat_provider or "").strip().lower()
    if provider in {"", "off", "none", "disabled"}:
        return None
    if provider == "cohere":
        if not settings.cohere_api_key:
            return None
        return CohereChatAdapter(
            api_key=settings.cohere_api_key,
            base_url=settings.cohere_base_url,
            chat_model=settings.chat_model,
            vision_model=settings.vision_model or "command-a-vision-07-2025",
            timeout_seconds=settings.chat_timeout_seconds,
        )
    return None
