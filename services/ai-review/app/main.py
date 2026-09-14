"""Codentry ai-review service entrypoint.

Phase 1 scope only: a health endpoint and logging/config wiring. Static
analysis (Phase 3), the Claude review engine (Phase 4), and the GitHub
webhook receiver (Phase 2) are deliberately not implemented here yet.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging import configure_logging

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


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
    }
