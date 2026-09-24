"""Codentry ai-review service entrypoint.

Phase 0 scope: GitHub App webhook ingestion with a durable event state
machine, a durable DB-backed review-job queue with a single in-process
worker, and deterministic static analysis (ESLint + Semgrep) with
differential (base -> head) classification. There is NO AI review here: no
Claude/LLM call, prompt, or AI finding exists in this service, and posting
comments to GitHub (Phase 5) is not implemented either.

Production fails closed: a production-like environment without a durable
store or the internal secret refuses to start (see Settings.startup_problems)
instead of running degraded.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging import configure_logging
from app.routes_internal import router as internal_router
from app.store import get_store
from app.worker import ReviewWorker

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("codentry.ai_review")

_worker: ReviewWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker

    problems = settings.startup_problems()
    if problems:
        message = "; ".join(problems)
        logger.error(
            "service_startup_refused environment=%s problems=%s", settings.environment, message
        )
        raise RuntimeError(f"refusing to start: {message}")

    logger.info(
        "service_startup environment=%s version=%s worker_enabled=%s",
        settings.environment,
        settings.service_version,
        settings.worker_enabled,
    )

    if settings.worker_enabled:
        # get_store() raises StoreConfigurationError if a durable store is
        # required but missing — surfaced here, at startup, not on first request.
        _worker = ReviewWorker(get_store(), settings)
        _worker.start()

    yield

    if _worker is not None:
        _worker.stop()
        _worker = None
    logger.info("service_shutdown")


# Interactive API docs and the OpenAPI schema enumerate every internal route;
# only expose them in development/test.
_docs_kwargs = (
    {}
    if settings.api_docs_enabled
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)

app = FastAPI(
    title="Codentry AI Review Service",
    version=settings.service_version,
    lifespan=lifespan,
    **_docs_kwargs,
)

app.include_router(internal_router)


@app.get("/health")
async def health() -> dict:
    """Liveness only. Deliberately reveals nothing about configuration."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "worker": "running" if _worker is not None and _worker.running else "not_running",
    }
