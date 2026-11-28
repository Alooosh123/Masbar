from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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

    # Application identity and signed-session configuration
    auth_required: bool = False
    google_client_id: str | None = None
    jwt_secret_key: str | None = None
    auth_token_ttl_minutes: int = Field(default=480, ge=5, le=1440)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    owner_password_reset_token: str | None = None
    owner_password_reset_password: str | None = None

    # Knowledge base
    kb_dir: Path = PROJECT_ROOT / "data" / "kb"
    oem_registry_path: Path = PROJECT_ROOT / "data" / "catalog" / "oem_registry.json"
    manual_index_dir: Path = PROJECT_ROOT / "data" / "manual_index"
    # Public manual excerpts stay disabled until the runtime is private or authenticated.
    manual_search_enabled: bool = False
    min_visual_confidence: float = 0.85
    demo_mode: bool = True

    # Sessions
    session_ttl_minutes: int = Field(default=240, ge=1, le=10080)
    session_db_path: Path = PROJECT_ROOT / "data" / "sessions" / "sessions.sqlite3"
    sqlite_backup_on_startup: bool = False
    sqlite_backup_dir: Path | None = None
    sqlite_backup_retention_days: int = Field(default=14, ge=1, le=365)

    # Vision provider: "mock" | "openai" | "cohere" | "openrouter"
    vision_provider: str = "mock"
    vision_model: str | None = None
    vision_timeout_seconds: float = 30.0

    # OpenAI-compatible providers
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

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
        return self.manual_search_enabled and (
            self.auth_required
            or self.environment.strip().lower() not in {"production", "prod"}
        )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def reject_wildcard_cors_in_production(self) -> "Settings":
        if self.auth_required and "*" in self.cors_origin_list:
            raise ValueError("AUTH_REQUIRED requires explicit CORS_ORIGINS for credentialed requests")
        if self.auth_required and (not self.jwt_secret_key or len(self.jwt_secret_key) < 32):
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters when AUTH_REQUIRED=true")
        if (
            self.environment.strip().lower() in {"production", "prod"}
            and "*" in self.cors_origin_list
        ):
            raise ValueError(
                "CORS_ORIGINS must list explicit trusted origins in production; wildcard CORS is refused"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
