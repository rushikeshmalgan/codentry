"""Phase 2 placeholder review execution.

This intentionally does nothing but prove the async lifecycle:

    pending -> running -> completed (0 findings)

No ESLint, no Semgrep, no Claude — those are Phase 3/4. No artificial delay
is added either; the point is to prove the plumbing, not to simulate
realistic review latency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.store import ReviewStore

logger = logging.getLogger("codentry.ai_review.review_runner")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_placeholder_review(store: ReviewStore, review_run_id: str) -> None:
    started_at = _now()
    try:
        store.update_review_run(review_run_id, status="running", started_at=started_at.isoformat())
    except Exception:
        logger.exception("review_run_start_failed review_run_id=%s", review_run_id)
        return

    logger.info("review_run_started review_run_id=%s", review_run_id)

    try:
        completed_at = _now()
        latency_ms = int((completed_at - started_at).total_seconds() * 1000)
        store.update_review_run(
            review_run_id,
            status="completed",
            completed_at=completed_at.isoformat(),
            latency_ms=latency_ms,
            error_message=None,
        )
        logger.info(
            "review_run_completed review_run_id=%s latency_ms=%d findings=0",
            review_run_id,
            latency_ms,
        )
    except Exception as exc:
        logger.exception("review_run_failed review_run_id=%s", review_run_id)
        try:
            store.update_review_run(
                review_run_id, status="failed", error_message=str(exc)[:500]
            )
        except Exception:
            logger.exception(
                "review_run_failure_not_recorded review_run_id=%s", review_run_id
            )
