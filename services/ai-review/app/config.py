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

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only environments where volatile in-memory state and interactive API
# docs are acceptable. Anything else (production, staging, or a typo) is
# treated as production-like: it must have a durable store and stays closed.
_LOOSE_ENVIRONMENTS = frozenset({"development", "test"})


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

    # --- Durable review worker (Phase 0) ---
    # A single in-process thread polls review_runs for due jobs. Disabled in
    # tests (which drive it directly); enable/disable explicitly elsewhere.
    worker_enabled: bool = True
    worker_poll_seconds: float = 2.0
    # How long a claimed job is owned before another worker may reclaim it.
    # Must exceed the worst-case analysis time; the worker also extends it.
    job_lease_seconds: int = 600
    job_max_attempts: int = 3

    # --- Not read until a later phase (AI review is NOT part of Phase 0) ---
    claude_api_key: str | None = None

    @field_validator("environment")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def is_loose_environment(self) -> bool:
        return self.environment in _LOOSE_ENVIRONMENTS

    @property
    def in_memory_store_allowed(self) -> bool:
        return self.is_loose_environment

    @property
    def api_docs_enabled(self) -> bool:
        return self.is_loose_environment

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    def startup_problems(self) -> list[str]:
        """Misconfigurations that must stop a production-like service from
        starting rather than let it run degraded and look healthy."""
        problems: list[str] = []
        if not self.is_loose_environment:
            if not self.supabase_configured:
                problems.append("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
            if not self.codentry_internal_webhook_secret:
                problems.append("CODENTRY_INTERNAL_WEBHOOK_SECRET is required")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
