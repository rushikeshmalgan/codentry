"""Durable, idempotent webhook event ingestion.

The old flow recorded a delivery id BEFORE doing the work, so any failure
after that point (a 500, a crash, a restart) turned every retry and every
GitHub "Redeliver" into a "duplicate" and the event was silently lost. Now:

    claim_delivery      -> `processing`, payload stored durably
    process_event       -> bookkeeping + idempotent job enqueue
    mark_delivery       -> `succeeded` ONLY after everything above committed

    exception in process_event:
        EventPayloadError   -> `failed`     (bad input; a retry will not help)
        anything else       -> `retryable`  (transient; reclaimable)
    crash before mark_delivery -> row stays `processing`; after the lease
        expires the sweeper (or a redelivery) reclaims it from the stored payload

Every step inside process_event is an upsert or an enqueue keyed on
(pull_request, head_sha), so re-running it for a reclaimed event is safe.

KNOWN REMAINING GAP (documented, not fixed here): all of the above starts
when the event reaches this service. If this service is unreachable when
GitHub's webhook lands on the Vercel edge (Render free-tier cold start, an
outage), apps/web forwards with a short timeout and returns 502; nothing
durable holds the event on the Vercel side, so it is recoverable only by a
manual GitHub "Redeliver". Closing that needs a Vercel-side inbox (an
insert-only table with HMAC re-verification on pickup) — recorded in
docs/architecture.md as the next architectural step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.events import (
    EventPayloadError,
    handle_installation_event,
    handle_installation_repositories_event,
    handle_pull_request_event,
)
from app.store import DELIVERY_LEASE_SECONDS, MAX_DELIVERY_ATTEMPTS, ReviewStore

logger = logging.getLogger("codentry.ai_review.ingest")


@dataclass(frozen=True)
class ProcessedEvent:
    review_run_id: str | None
    reason: str | None
    # True only for a pull_request event that produced no review job
    # (unsupported action, inactive repo, stale event). Installation events
    # are fully handled, not "ignored".
    ignored: bool = False


def process_event(
    store: ReviewStore, event_type: str, payload: dict[str, Any], delivery_id: str
) -> ProcessedEvent:
    """Runs the (idempotent) side effects of one event. Raises EventPayloadError
    for unusable payloads; any other exception is treated as transient."""
    if event_type == "installation":
        result = handle_installation_event(store, payload)
        logger.info(
            "installation_event_processed delivery_id=%s action=%s",
            delivery_id,
            result.get("action"),
        )
        return ProcessedEvent(None, None)

    if event_type == "installation_repositories":
        result = handle_installation_repositories_event(store, payload)
        logger.info(
            "installation_repositories_event_processed delivery_id=%s action=%s "
            "added=%s removed=%s",
            delivery_id,
            result.get("action"),
            result.get("added"),
            result.get("removed"),
        )
        return ProcessedEvent(None, None)

    # event_type == "pull_request" (the only remaining Literal option)
    result = handle_pull_request_event(store, payload, delivery_id=delivery_id)
    logger.info(
        "pull_request_event_processed delivery_id=%s action=%s review_run_id=%s reason=%s",
        delivery_id,
        result.get("action"),
        result.get("review_run_id"),
        result.get("reason"),
    )
    review_run_id = result.get("review_run_id")
    return ProcessedEvent(review_run_id, result.get("reason"), ignored=review_run_id is None)


def sweep_deliveries(
    store: ReviewStore, now: datetime | None = None, limit: int = 20
) -> dict[str, int]:
    """Reprocesses `retryable` and stale-`processing` deliveries from their
    stored payloads. Deliveries that have used all their attempts are marked
    `failed` (permanently) rather than being retried forever."""
    counts = {"reprocessed": 0, "failed_permanently": 0, "skipped": 0}
    for row in store.list_reclaimable_deliveries(now=now, limit=limit):
        delivery_id = row["delivery_id"]

        if row["attempts"] >= MAX_DELIVERY_ATTEMPTS:
            store.mark_delivery(delivery_id, "failed", "max_delivery_attempts_exceeded")
            counts["failed_permanently"] += 1
            continue
        if not row.get("payload"):
            store.mark_delivery(delivery_id, "failed", "no_stored_payload")
            counts["failed_permanently"] += 1
            continue

        claim = store.claim_delivery(
            delivery_id,
            row["event_type"],
            row["payload"],
            now=now,
            lease_seconds=DELIVERY_LEASE_SECONDS,
        )
        if claim.state not in ("new", "reclaimed"):
            counts["skipped"] += 1
            continue

        try:
            process_event(store, row["event_type"], row["payload"], delivery_id)
        except EventPayloadError as exc:
            store.mark_delivery(delivery_id, "failed", str(exc))
            counts["failed_permanently"] += 1
        except Exception as exc:
            logger.exception("delivery_sweep_failed delivery_id=%s", delivery_id)
            store.mark_delivery(delivery_id, "retryable", type(exc).__name__)
        else:
            store.mark_delivery(delivery_id, "succeeded")
            counts["reprocessed"] += 1
    return counts
