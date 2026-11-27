from functools import lru_cache
import logging

from app.adapters.chat.factory import build_chat_adapter
from app.adapters.tts.edge import EdgeTtsAdapter
from app.adapters.vision.factory import build_vision_adapter
from app.core.config import Settings, get_settings
from app.knowledge.loader import KnowledgeBase, load_knowledge_base
from app.knowledge.manual_index import ManualLibrary
from app.knowledge.oem import OemRegistry, load_oem_registry
from app.knowledge.retrieval import HybridRetriever
from app.safety.guard import SafetyGuard
from app.services.assistant import AssistantService
from app.services.chat import ChatService
from app.services.session import SessionStore
from app.services.conversation import ConversationStore
from app.security.auth import AuthStore


logger = logging.getLogger(__name__)


@lru_cache
def get_auth_store() -> AuthStore:
    settings = get_settings()
    store = AuthStore(
        settings.session_db_path,
        auth_required=settings.auth_required,
        bootstrap_email=settings.bootstrap_admin_email,
        bootstrap_password=settings.bootstrap_admin_password,
    )

    reset_token = settings.owner_password_reset_token
    reset_password = settings.owner_password_reset_password
    if bool(reset_token) != bool(reset_password):
        raise RuntimeError(
            "OWNER_PASSWORD_RESET_TOKEN and OWNER_PASSWORD_RESET_PASSWORD must be set together"
        )
    if reset_token and reset_password:
        recovered_owner = store.reset_primary_owner_password_once(reset_token, reset_password)
        if recovered_owner is not None:
            logger.warning(
                "One-time owner password recovery completed for %s; remove the recovery variables from the deployment.",
                recovered_owner.email,
            )
    return store


@lru_cache
def get_kb() -> KnowledgeBase:
    settings = get_settings()
    return load_knowledge_base(settings.kb_dir)


@lru_cache
def get_manual_library() -> ManualLibrary:
    settings = get_settings()
    return ManualLibrary.load(settings.manual_index_dir)


@lru_cache
def get_oem_registry() -> OemRegistry:
    settings = get_settings()
    return load_oem_registry(settings.oem_registry_path)


@lru_cache
def get_retriever() -> HybridRetriever:
    return HybridRetriever(get_kb())


@lru_cache
def get_conversation_store() -> ConversationStore:
    settings = get_settings()
    return ConversationStore(settings.session_db_path)


@lru_cache
def get_store() -> SessionStore:
    settings = get_settings()
    return SessionStore(
        ttl_minutes=settings.session_ttl_minutes,
        db_path=settings.session_db_path,
    )


@lru_cache
def get_assistant() -> AssistantService:
    settings: Settings = get_settings()
    kb = get_kb()
    return AssistantService(
        kb=kb,
        guard=SafetyGuard(kb, min_visual_confidence=settings.min_visual_confidence),
        retriever=get_retriever(),
        store=get_store(),
        vision=build_vision_adapter(kb, settings),
        settings=settings,
    )


@lru_cache
def get_chat_service() -> ChatService:
    settings: Settings = get_settings()
    return ChatService(
        assistant=get_assistant(),
        kb=get_kb(),
        store=get_store(),
        chat=build_chat_adapter(settings),
        settings=settings,
    )


@lru_cache
def get_tts_adapter() -> EdgeTtsAdapter:
    settings: Settings = get_settings()
    return EdgeTtsAdapter(
        default_voice=settings.tts_voice,
        timeout_seconds=settings.tts_timeout_seconds,
        cache_dir=settings.tts_cache_dir,
    )


def reset_caches() -> None:
    """Used by tests when environment variables change between cases."""
    get_auth_store.cache_clear()
    get_kb.cache_clear()
    get_oem_registry.cache_clear()
    get_manual_library.cache_clear()
    get_retriever.cache_clear()
    get_store.cache_clear()
    get_conversation_store.cache_clear()
    get_assistant.cache_clear()
    get_chat_service.cache_clear()
    get_tts_adapter.cache_clear()
    get_settings.cache_clear()
