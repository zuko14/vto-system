"""
ZukoLabs VTO — Application Configuration

Loads all settings from environment variables using pydantic-settings.
Never hardcode secrets. Never commit .env.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Meta WhatsApp Cloud API ──────────────────────────────
    whatsapp_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""

    # ── Supabase ─────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""

    # ── Groq LLM ─────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Replicate (Try-On Engine) ────────────────────────────
    replicate_api_token: str = ""
    replicate_viton_model: str = "yisol/idm-vton"

    # ── App Settings ─────────────────────────────────────────
    app_env: str = "development"
    base_url: str = ""
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def whatsapp_api_url(self) -> str:
        return "https://graph.facebook.com/v21.0"


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached singleton of the application settings.
    Call this instead of instantiating Settings() directly.
    """
    return Settings()
