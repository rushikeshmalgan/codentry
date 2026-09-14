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
    status: Literal["accepted", "duplicate_ignored", "ignored"]
    review_run_id: str | None = None
    reason: str | None = None


class ReviewRunStatusResponse(BaseModel):
    id: str
    pull_request_id: str
    trigger_event: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: int | None = None
    error_message: str | None = None


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
