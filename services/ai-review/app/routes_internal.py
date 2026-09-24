"""The internal Vercel -> Render API surface.

Every route here requires X-Codentry-Internal-Secret (see app/internal_auth.py)
and is never intended to be reachable directly from the public internet
without it — see docs/deployment.md for how Render should be configured.

The webhook endpoint no longer runs a review itself. It durably records the
event, performs idempotent bookkeeping, and enqueues a job row; the worker
(app/worker.py) executes jobs. See app/ingest.py for the delivery state
machine and why `succeeded` is only written after everything else committed.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.events import EventPayloadError
from app.ingest import process_event
from app.internal_auth import require_internal_secret
from app.schemas import (
    InstallationSummary,
    InternalWebhookEnvelope,
    ReviewRunStatusResponse,
    WebhookAcceptedResponse,
)
from app.store import ReviewStore, get_store

logger = logging.getLogger("codentry.ai_review.routes_internal")

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_secret)])


def _best_effort_mark(store: ReviewStore, delivery_id: str, outcome: str, error: str) -> None:
    try:
        store.mark_delivery(delivery_id, outcome, error)  # type: ignore[arg-type]
    except Exception:
        # The row stays `processing`; the sweeper reclaims it after the lease.
        logger.exception("delivery_outcome_not_recorded delivery_id=%s", delivery_id)


@router.post(
    "/webhook/pull-request",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def receive_webhook_event(
    envelope: InternalWebhookEnvelope,
    store: ReviewStore = Depends(get_store),
) -> WebhookAcceptedResponse:
    claim = store.claim_delivery(envelope.delivery_id, envelope.event_type, envelope.payload)

    if claim.state == "duplicate":
        logger.info(
            "webhook_delivery_duplicate delivery_id=%s event_type=%s",
            envelope.delivery_id,
            envelope.event_type,
        )
        return WebhookAcceptedResponse(status="duplicate_ignored")
    if claim.state == "in_progress":
        logger.info("webhook_delivery_in_progress delivery_id=%s", envelope.delivery_id)
        return WebhookAcceptedResponse(status="in_progress")

    try:
        processed = process_event(
            store, envelope.event_type, envelope.payload, envelope.delivery_id
        )
    except EventPayloadError as exc:
        logger.warning(
            "webhook_payload_rejected delivery_id=%s event_type=%s reason=%s",
            envelope.delivery_id,
            envelope.event_type,
            str(exc),
        )
        _best_effort_mark(store, envelope.delivery_id, "failed", str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("webhook_processing_failed delivery_id=%s", envelope.delivery_id)
        _best_effort_mark(store, envelope.delivery_id, "retryable", type(exc).__name__)
        # Generic on purpose: never echo internal exception text to the caller.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="processing_failed"
        ) from exc

    try:
        store.mark_delivery(envelope.delivery_id, "succeeded")
    except Exception as exc:
        # Side effects committed but the outcome was not recorded: the row stays
        # `processing`, and reprocessing is idempotent. Report failure so the
        # sender retries instead of assuming the event is fully settled.
        logger.exception("delivery_success_not_recorded delivery_id=%s", envelope.delivery_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="processing_failed"
        ) from exc

    if processed.ignored:
        return WebhookAcceptedResponse(status="ignored", reason=processed.reason)
    return WebhookAcceptedResponse(status="accepted", review_run_id=processed.review_run_id)


def _run_response(row: dict) -> ReviewRunStatusResponse:
    return ReviewRunStatusResponse(
        id=row["id"],
        pull_request_id=row["pull_request_id"],
        trigger_event=row["trigger_event"],
        status=row["status"],
        head_sha=row.get("head_sha"),
        base_sha=row.get("base_sha"),
        merge_base_sha=row.get("merge_base_sha"),
        attempts=row.get("attempts") or 0,
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        latency_ms=row.get("latency_ms"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        analysis_meta=row.get("analysis_meta"),
    )


@router.get("/review-runs/{review_run_id}", response_model=ReviewRunStatusResponse)
def get_review_run_status(
    review_run_id: str, store: ReviewStore = Depends(get_store)
) -> ReviewRunStatusResponse:
    row = store.get_review_run(review_run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review_run_not_found")
    return _run_response(row)


@router.post("/review-runs/{review_run_id}/retry", response_model=ReviewRunStatusResponse)
def retry_review_run(
    review_run_id: str, store: ReviewStore = Depends(get_store)
) -> ReviewRunStatusResponse:
    """Manual retry of a `failed` run (the only way a failed run leaves that
    state). Any other status is a 409: completed/partial/superseded runs are
    final, and pending/running ones are already being handled."""
    if store.get_review_run(review_run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review_run_not_found")
    row = store.retry_review_run(review_run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="review_run_not_failed")
    logger.info("review_run_manually_retried review_run_id=%s", review_run_id)
    return _run_response(row)


@router.get("/installations", response_model=list[InstallationSummary])
def list_installations(store: ReviewStore = Depends(get_store)) -> list[InstallationSummary]:
    """Backs the internal debugging view (apps/web/app/internal/installations).

    Same internal-secret gate as everything else in this router. The Next.js
    page that displays it is itself disabled unless explicitly enabled and is
    behind HTTP Basic auth (apps/web/middleware.ts).
    """
    return [InstallationSummary(**row) for row in store.list_installations_summary()]
