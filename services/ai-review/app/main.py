"""Codentry ai-review service entrypoint.

Phase 2 scope: GitHub App webhook bookkeeping and the async placeholder
pipeline (pending -> running -> completed, 0 findings). Static analysis
(Phase 3), the Claude review engine (Phase 4), and actually posting to
GitHub (Phase 5) are deliberately not implemented here yet.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging import configure_logging
from app.routes_internal import router as internal_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("codentry.ai_review")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "service_startup environment=%s version=%s",
        settings.environment,
        settings.service_version,
    )
    yield
    logger.info("service_shutdown")


app = FastAPI(
    title="Codentry AI Review Service",
    version=settings.service_version,
    lifespan=lifespan,
)

app.include_router(internal_router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
    }
