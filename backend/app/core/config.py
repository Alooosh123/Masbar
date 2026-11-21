from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> core -> app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or the root .env file."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Industrial Spatial AI Assistant"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    cors_origins: str = "*"

    # Knowledge base
    kb_dir: Path = PROJECT_ROOT / "data" / "kb"
    oem_registry_path: Path = PROJECT_ROOT / "data" / "catalog" / "oem_registry.json"
    manual_index_dir: Path = PROJECT_ROOT / "data" / "manual_index"
    # Public manual excerpts stay disabled until the runtime is private or authenticated.
    manual_search_enabled: bool = False
    min_visual_confidence: float = 0.85
    demo_mode: bool = True

    # Sessions
    session_ttl_minutes: int = 240

    # Vision provider: "mock" | "openai" | "cohere"
    vision_provider: str = "mock"
    vision_model: str | None = None
    vision_timeout_seconds: float = 30.0

    # OpenAI-compatible provider (also works with OpenRouter and similar gateways)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Cohere Chat v2 provider (native endpoint with JSON schema support)
    cohere_api_key: str | None = None
    cohere_base_url: str = "https://api.cohere.com/v2"

    # General conversation (separate from the safety-critical vision adapter)
    chat_provider: str = "cohere"
    chat_model: str = "command-a-plus-05-2026"
    chat_timeout_seconds: float = 45.0

    # Arabic text-to-speech (neural voices only)
    tts_provider: str = "edge"
    tts_voice: str = "ar-SA-ZariyahNeural"
    tts_timeout_seconds: float = 25.0
    tts_cache_dir: Path = PROJECT_ROOT / "data" / "cache" / "tts"

    @property
    def manual_search_available(self) -> bool:
        """Manual excerpts are unavailable in production until auth/RBAC exists."""
        return self.manual_search_enabled and self.environment.strip().lower() not in {
            "production",
            "prod",
        }

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
