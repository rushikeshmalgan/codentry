"""Environment-driven configuration for the ai-review service.

Every variable this service will ever need — including ones not read by any
code until a later phase — is declared here with an explicit comment, so the
full env surface is documented from Phase 1 onward instead of growing
silently. Nothing here is assumed to be set; everything defaults to None or a
safe development value.

Field names intentionally match the env var names verbatim (pydantic-settings
maps `github_private_key` -> `GITHUB_PRIVATE_KEY` automatically) so there is
one obvious place to look for "what does this env var actually feed."
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
    service_version: str = "0.2.0"

    # --- Phase 2: internal Vercel -> Render boundary ---
    # Deliberately distinct from GITHUB_WEBHOOK_SECRET (which this service
    # never sees at all — HMAC verification happens in apps/web). Compromise
    # of one secret must not compromise the other.
    codentry_internal_webhook_secret: str | None = None

    # --- Phase 2: GitHub App authentication (JWT -> installation token) ---
    github_app_id: str | None = None
    # PEM, typically stored in the platform env var with literal "\n"
    # sequences instead of real newlines (most dashboards don't accept
    # multiline values cleanly). app/github_auth.py un-escapes this before
    # use. Never logged, never returned by any endpoint.
    github_private_key: str | None = None

    # --- Phase 2: Supabase (also used from Phase 9 onward for pgvector) ---
    supabase_url: str | None = None
    # Backend-only. Must never reach apps/web's client bundle.
    supabase_service_role_key: str | None = None

    # --- Not read until Phase 4 (Claude AI review engine) ---
    claude_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
