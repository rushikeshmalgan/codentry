"""Pydantic contracts for the Phase 2 internal API surface.

Kept intentionally small: GitHub's real payloads are large, and modeling
them fully is scope creep for a phase whose job is proving the async
plumbing, not the review pipeline. We validate the envelope strictly and
extract only the handful of fields each handler actually needs, defensively,
inside app/events.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SupportedEventType = Literal["pull_request", "installation", "installation_repositories"]


class InternalWebhookEnvelope(BaseModel):
    """The contract for POST /internal/webhook/pull-request.

    Despite the URL's name (kept as specified), this single endpoint accepts
    all three supported GitHub event types and dispatches on `event_type`.
    """

    delivery_id: str = Field(min_length=1)
    event_type: SupportedEventType
    payload: dict[str, Any]


class WebhookAcceptedResponse(BaseModel):
    # duplicate_ignored: already SUCCEEDED (safe to ignore)
    # in_progress:       another handler holds it right now
    status: Literal["accepted", "duplicate_ignored", "ignored", "in_progress"]
    review_run_id: str | None = None
    reason: str | None = None


class ReviewRunStatusResponse(BaseModel):
    id: str
    pull_request_id: str
    trigger_event: str
    # pending | running | completed | partial | failed | superseded
    status: str
    head_sha: str | None = None
    base_sha: str | None = None
    merge_base_sha: str | None = None
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    analysis_meta: dict[str, Any] | None = None


class InstallationSummary(BaseModel):
    account_login: str | None
    account_type: str | None
    github_installation_id: int
    repository_count: int
    repositories: list["RepositorySummary"]


class RepositorySummary(BaseModel):
    full_name: str
    is_active: bool


InstallationSummary.model_rebuild()
