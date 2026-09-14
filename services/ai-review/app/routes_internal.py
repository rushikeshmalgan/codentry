"""The internal Vercel -> Render API surface.

Every route here requires X-Codentry-Internal-Secret (see app/internal_auth.py)
and is never intended to be reachable directly from the public internet
without it — see docs/deployment.md for how Render should be configured.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.events import (
    EventPayloadError,
    handle_installation_event,
    handle_installation_repositories_event,
    handle_pull_request_event,
)
from app.internal_auth import require_internal_secret
from app.review_runner import run_placeholder_review
from app.schemas import (
    InstallationSummary,
    InternalWebhookEnvelope,
    ReviewRunStatusResponse,
    WebhookAcceptedResponse,
)
from app.store import ReviewStore, get_store

logger = logging.getLogger("codentry.ai_review.routes_internal")

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_secret)])


@router.post(
    "/webhook/pull-request",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def receive_webhook_event(
    envelope: InternalWebhookEnvelope,
    background_tasks: BackgroundTasks,
    store: ReviewStore = Depends(get_store),
) -> WebhookAcceptedResponse:
    is_new = store.record_delivery(envelope.delivery_id, envelope.event_type)
    if not is_new:
        logger.info(
            "webhook_delivery_duplicate delivery_id=%s event_type=%s",
            envelope.delivery_id,
            envelope.event_type,
        )
        return WebhookAcceptedResponse(status="duplicate_ignored")

    try:
        if envelope.event_type == "installation":
            result = handle_installation_event(store, envelope.payload)
            logger.info(
                "installation_event_processed delivery_id=%s action=%s",
                envelope.delivery_id,
                result.get("action"),
            )
            return WebhookAcceptedResponse(status="accepted")

        if envelope.event_type == "installation_repositories":
            result = handle_installation_repositories_event(store, envelope.payload)
            logger.info(
                "installation_repositories_event_processed delivery_id=%s action=%s "
                "added=%s removed=%s",
                envelope.delivery_id,
                result.get("action"),
                result.get("added"),
                result.get("removed"),
            )
            return WebhookAcceptedResponse(status="accepted")

        # event_type == "pull_request" (the only remaining Literal option)
        result = handle_pull_request_event(store, envelope.payload)
        review_run_id = result.get("review_run_id")

        if review_run_id is None:
            logger.info(
                "pull_request_event_skipped delivery_id=%s action=%s reason=%s",
                envelope.delivery_id,
                result.get("action"),
                result.get("reason"),
            )
            return WebhookAcceptedResponse(status="ignored", reason=result.get("reason"))

        background_tasks.add_task(run_placeholder_review, store, review_run_id)
        logger.info(
            "pull_request_event_accepted delivery_id=%s action=%s review_run_id=%s",
            envelope.delivery_id,
            result.get("action"),
            review_run_id,
        )
        return WebhookAcceptedResponse(status="accepted", review_run_id=review_run_id)

    except EventPayloadError as exc:
        logger.warning(
            "webhook_payload_rejected delivery_id=%s event_type=%s reason=%s",
            envelope.delivery_id,
            envelope.event_type,
            str(exc),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/review-runs/{review_run_id}", response_model=ReviewRunStatusResponse)
def get_review_run_status(
    review_run_id: str, store: ReviewStore = Depends(get_store)
) -> ReviewRunStatusResponse:
    row = store.get_review_run(review_run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review_run_not_found")
    return ReviewRunStatusResponse(
        id=row["id"],
        pull_request_id=row["pull_request_id"],
        trigger_event=row["trigger_event"],
        status=row["status"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        latency_ms=row.get("latency_ms"),
        error_message=row.get("error_message"),
    )


@router.get("/installations", response_model=list[InstallationSummary])
def list_installations(store: ReviewStore = Depends(get_store)) -> list[InstallationSummary]:
    """Backs the internal debugging view (apps/web/app/internal/installations).

    Not listed in the Phase-2 spec's API summary table, which only names the
    webhook and review-run endpoints — added because section 17 explicitly
    asks for an internal installations view, and per Phase 1's architecture
    apps/web never holds Supabase credentials, so Next.js has no way to get
    this data without a small backend endpoint. Same internal-secret gate as
    everything else in this router.
    """
    return [InstallationSummary(**row) for row in store.list_installations_summary()]
