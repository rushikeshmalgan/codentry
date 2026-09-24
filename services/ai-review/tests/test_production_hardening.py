"""Production must fail closed; internal surfaces must not leak."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.store import (
    InMemoryReviewStore,
    StoreConfigurationError,
    get_store,
    reset_store_singleton_for_tests,
)

SERVICE_ROOT = Path(__file__).parent.parent


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# --- fail closed --------------------------------------------------------------


@pytest.mark.parametrize("environment", ["production", "staging", "prod", "Production", "typo"])
def test_anything_but_development_or_test_requires_a_durable_store_and_the_internal_secret(environment):
    problems = _settings(
        environment=environment, codentry_internal_webhook_secret=None
    ).startup_problems()
    assert any("SUPABASE" in p for p in problems)
    assert any("CODENTRY_INTERNAL_WEBHOOK_SECRET" in p for p in problems)


def test_a_fully_configured_production_environment_has_no_startup_problems():
    settings = _settings(
        environment="production",
        supabase_url="https://x.supabase.co",
        supabase_service_role_key="k",
        codentry_internal_webhook_secret="s",
    )
    assert settings.startup_problems() == []


@pytest.mark.parametrize("environment", ["development", "test", "Development"])
def test_development_and_test_may_run_without_a_database(environment):
    settings = _settings(environment=environment)
    assert settings.startup_problems() == []
    assert settings.in_memory_store_allowed is True


def test_production_refuses_to_use_the_in_memory_store(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    reset_store_singleton_for_tests()
    try:
        with pytest.raises(StoreConfigurationError):
            get_store()
    finally:
        monkeypatch.setenv("ENVIRONMENT", "test")
        get_settings.cache_clear()
        reset_store_singleton_for_tests()


def test_test_environment_falls_back_to_the_in_memory_store(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    reset_store_singleton_for_tests()
    try:
        assert isinstance(get_store(), InMemoryReviewStore)
    finally:
        get_settings.cache_clear()
        reset_store_singleton_for_tests()


def test_the_service_refuses_to_start_when_production_config_is_missing(monkeypatch):
    import app.main as main

    monkeypatch.setattr(
        main, "settings", _settings(environment="production", worker_enabled=False)
    )

    async def start():
        async with main.lifespan(FastAPI()):
            pass

    with pytest.raises(RuntimeError, match="refusing to start"):
        asyncio.run(start())


def _run_python(code: str, **env) -> str:
    full_env = {**os.environ, **env}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SERVICE_ROOT, capture_output=True, text=True, timeout=60, env=full_env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_api_docs_and_openapi_are_off_in_production_for_real():
    out = _run_python(
        "import app.main as m; print(m.app.docs_url, m.app.redoc_url, m.app.openapi_url)",
        ENVIRONMENT="production",
        CODENTRY_INTERNAL_WEBHOOK_SECRET="x",
    )
    assert out == "None None None"


def test_api_docs_remain_available_in_development():
    out = _run_python(
        "import app.main as m; print(m.app.docs_url, m.app.openapi_url)",
        ENVIRONMENT="development",
    )
    assert out == "/docs /openapi.json"


# --- no information leaks -------------------------------------------------------


def test_health_reveals_nothing_about_configuration(client):
    body = client.get("/health").json()
    assert set(body) == {"status", "service", "version", "worker"}
    assert "environment" not in body


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/internal/webhook/pull-request"),
        ("get", "/internal/review-runs/x"),
        ("post", "/internal/review-runs/x/retry"),
        ("get", "/internal/installations"),
    ],
)
def test_every_internal_route_requires_the_internal_secret(client, method, path):
    kwargs = {"json": {}} if method == "post" and "webhook" in path else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    wrong = getattr(client, method)(path, headers={"X-Codentry-Internal-Secret": "nope"}, **kwargs)
    assert wrong.status_code == 401


def test_internal_routes_fail_closed_if_the_secret_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("CODENTRY_INTERNAL_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        resp = client.get("/internal/installations", headers={"X-Codentry-Internal-Secret": "anything"})
        assert resp.status_code == 503
    finally:
        monkeypatch.setenv("CODENTRY_INTERNAL_WEBHOOK_SECRET", "test-internal-secret-do-not-use-in-prod")
        get_settings.cache_clear()
