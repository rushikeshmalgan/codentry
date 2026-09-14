"""Environment-driven configuration for the ai-review service.

Every variable this service will ever need — including ones not read by any
code until a later phase — is declared here with an explicit comment, so the
full env surface is documented from Phase 1 onward instead of growing
silently. Nothing here is assumed to be set; everything defaults to None or a
safe development value.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Phase 1 ---
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    service_name: str = "codentry-ai-review"
    service_version: str = "0.1.0"

    # --- Not read until Phase 2 (GitHub App integration) ---
    internal_handoff_secret: str | None = None
    github_app_id: str | None = None
    github_app_private_key: str | None = None
    github_webhook_secret: str | None = None

    # --- Not read until Phase 2 (Supabase) / Phase 9 (pgvector) ---
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # --- Not read until Phase 4 (Claude AI review engine) ---
    claude_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
