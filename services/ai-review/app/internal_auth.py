"""Authentication for the Vercel -> Render internal boundary.

Deliberately separate from GitHub's own webhook HMAC secret (see
app/config.py). Never logs the header or the configured secret — only
whether a request was accepted or rejected.
"""

import hmac
import logging

from fastapi import Header, HTTPException, status

from app.config import get_settings

logger = logging.getLogger("codentry.ai_review.internal_auth")

INTERNAL_SECRET_HEADER = "x-codentry-internal-secret"


def require_internal_secret(
    x_codentry_internal_secret: str | None = Header(default=None, alias="X-Codentry-Internal-Secret"),
) -> None:
    settings = get_settings()
    configured = settings.codentry_internal_webhook_secret

    if not configured:
        # Fail closed: an unset secret must never be treated as "any value
        # is fine." This only happens if the service is misconfigured.
        logger.error("internal_auth_rejected reason=secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal_auth_not_configured",
        )

    if not x_codentry_internal_secret:
        logger.warning("internal_auth_rejected reason=missing_header")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_internal_secret")

    if not hmac.compare_digest(x_codentry_internal_secret, configured):
        logger.warning("internal_auth_rejected reason=invalid_secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")
