from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    manual_search_enabled: bool = False
    min_visual_confidence: float = 0.85
    demo_mode: bool = True

    # Sessions and identities share the persistent data mount in production.
    session_ttl_minutes: int = Field(default=240, ge=1, le=10080)
    session_db_path: Path = PROJECT_ROOT / "data" / "sessions" / "sessions.sqlite3"
    auth_db_path: Path = PROJECT_ROOT / "data" / "sessions" / "auth.sqlite3"
    auth_enabled: bool = False
    auth_token_secret: str | None = None
    auth_setup_token: str | None = None
    auth_token_ttl_hours: int = Field(default=12, ge=1, le=168)

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
        """In production, manual excerpts are available only after auth is enabled."""
        production = self.environment.strip().lower() in {"production", "prod"}
        return self.manual_search_enabled and (not production or self.auth_enabled)

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        production = self.environment.strip().lower() in {"production", "prod"}
        if production and "*" in self.cors_origin_list:
            raise ValueError(
                "CORS_ORIGINS must list explicit trusted origins in production; wildcard CORS is refused"
            )
        if production and self.auth_enabled:
            if not self.auth_token_secret or len(self.auth_token_secret) < 32:
                raise ValueError("AUTH_TOKEN_SECRET must contain at least 32 characters in production")
            if not self.auth_setup_token or len(self.auth_setup_token) < 24:
                raise ValueError("AUTH_SETUP_TOKEN must contain at least 24 characters in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
