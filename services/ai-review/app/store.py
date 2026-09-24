"""Data access layer: bookkeeping, durable webhook events, and durable review jobs.

Two implementations share one interface:

- `InMemoryReviewStore` — process-local and lock-protected. Used by the test
  suite and as an explicit fallback ONLY in `development`/`test`. It is never
  used in any other environment: get_store() raises instead (production must
  fail closed rather than quietly run on volatile state).

- `SupabaseReviewStore` — the real implementation over PostgREST, backed by
  supabase/migrations/0001..0004. NOT exercised against a live Supabase
  project in development (no credentials were available); race-safety
  claims below are by construction (conditional updates) and are covered by
  the in-memory store's tests of the same contract, not by a live database.

Two state machines live here (full description in docs/architecture.md):

  webhook_deliveries   processing -> succeeded | failed | retryable
      Only `succeeded` is a duplicate. `failed`/`retryable` and a stale
      `processing` (crashed handler) are reclaimable, so an event is never
      lost merely because a previous attempt died.

  review_runs (the job)  pending -> running -> completed | partial | failed
                         running -> pending (lease expiry / retryable error)
                         pending|running -> superseded (newer head commit)
                         failed -> pending (explicit manual retry only)
      Claiming is a compare-and-swap; `attempts` is a fencing token, so a
      worker that lost its lease cannot overwrite the current attempt.

Both stores are intentionally synchronous (the Supabase client is).
"""

from __future__ import annotations

import logging
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from analysis.finding import Finding

logger = logging.getLogger("codentry.ai_review.store")

DELIVERY_LEASE_SECONDS = 120  # a healthy handler finishes bookkeeping far sooner
MAX_DELIVERY_ATTEMPTS = 5
DEFAULT_MAX_JOB_ATTEMPTS = 3

DeliveryState = Literal["new", "reclaimed", "duplicate", "in_progress"]
DeliveryOutcome = Literal["succeeded", "failed", "retryable"]
RunStatus = Literal["pending", "running", "completed", "partial", "failed", "superseded"]


class StoreConfigurationError(RuntimeError):
    """The configured environment requires a durable store that is not configured."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | datetime | None) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class DeliveryClaim:
    state: DeliveryState
    attempts: int


@dataclass(frozen=True)
class JobContext:
    review_run: dict[str, Any]
    pull_request: dict[str, Any]
    repository: dict[str, Any]
    installation: dict[str, Any]


def finding_row(review_run_id: str, f: Finding) -> dict[str, Any]:
    return {
        "review_run_id": review_run_id,
        "source": f.source,
        "category": f.category,
        "severity": f.severity,
        "confidence": f.confidence,
        "title": f.title,
        "description": f.description,
        "file_path": f.file_path,
        "start_line": f.start_line,
        "end_line": f.end_line,
        "suggestion": f.suggestion,
        "reasoning": f.reasoning,
        "evidence_span": f.evidence_span,
        "dedup_hash": f.dedup_hash,
        "identity_key": f.identity_key,
        "change_status": f.change_status,
        "moved": f.moved,
        "in_diff": f.in_diff,
        "base_start_line": f.base_start_line,
    }


class ReviewStore(ABC):
    # ------------------------------------------------------------------
    # webhook deliveries (durable, idempotent)
    # ------------------------------------------------------------------
    @abstractmethod
    def claim_delivery(
        self,
        delivery_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
    ) -> DeliveryClaim:
        """Atomically claim `delivery_id` for processing.

        new         first time seen; recorded as `processing` with the payload
        reclaimed   a prior attempt failed/was retryable/crashed (stale
                    `processing`); this caller now owns it
        duplicate   already `succeeded` — do nothing
        in_progress another handler is working on it right now
        """

    @abstractmethod
    def mark_delivery(
        self, delivery_id: str, outcome: DeliveryOutcome, error: str | None = None
    ) -> None:
        """Record the outcome. Only call `succeeded` after ALL side effects committed."""

    @abstractmethod
    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def list_reclaimable_deliveries(
        self,
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """`retryable` rows plus `processing` rows whose lease has expired."""

    # ------------------------------------------------------------------
    # installations / repositories / pull requests
    # ------------------------------------------------------------------
    @abstractmethod
    def upsert_installation(
        self,
        github_installation_id: int,
        account_login: str | None,
        account_type: str | None,
    ) -> dict[str, Any]:
        """Create or update an installation row.

        Never overwrites an existing account_login/account_type with None —
        a pull_request event only carries the installation id, and must not
        clobber details a prior `installation` event already recorded.
        """

    @abstractmethod
    def deactivate_repositories_for_installation(self, github_installation_id: int) -> int:
        """Set is_active=false for every repo under this installation. Returns count affected."""

    @abstractmethod
    def upsert_repository(
        self,
        installation_row_id: str,
        github_repo_id: int,
        full_name: str,
        default_branch: str | None,
    ) -> dict[str, Any]:
        """Create or update a repository row.

        On the update path, is_active is deliberately left untouched — this
        method must never silently reactivate a repo the team turned off.
        New rows default to is_active=true (installing/authorizing the App
        on a repo is itself the team's explicit enable action).
        """

    @abstractmethod
    def set_repository_active(self, github_repo_id: int, is_active: bool) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def get_repository_by_github_id(self, github_repo_id: int) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def upsert_pull_request(
        self,
        repository_id: str,
        github_pr_number: int,
        title: str | None,
        author_login: str | None,
        head_sha: str | None,
        base_sha: str | None,
        state: str | None,
        github_updated_at: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a PR row.

        Stale-event guard: if `github_updated_at` is older than what is
        already stored, nothing is overwritten and the returned row carries
        `stale_event=True` (an older event delivered late must not rewind the
        PR's head SHA).
        """

    @abstractmethod
    def get_pull_request(self, pull_request_id: str) -> dict[str, Any] | None:
        pass

    # ------------------------------------------------------------------
    # review runs = durable jobs
    # ------------------------------------------------------------------
    @abstractmethod
    def enqueue_review_run(
        self,
        pull_request_id: str,
        trigger_event: str,
        head_sha: str | None,
        base_sha: str | None,
        delivery_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Idempotent on (pull_request_id, head_sha). Returns (run, created).

        Creating a run supersedes every OTHER still-`pending` run of the same
        PR (a newer head makes older pending work pointless). A `running`
        older run is left to notice at fetch/finalize time that its head is
        no longer current.
        """

    @abstractmethod
    def claim_next_review_run(
        self, lease_seconds: int, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """Atomically take one due job (pending and available, or running with
        an expired lease), incrementing `attempts` and setting the lease.
        A running job whose lease expired with attempts exhausted is failed
        (`max_attempts_exceeded`) instead of being retried forever."""

    @abstractmethod
    def extend_lease(
        self, review_run_id: str, attempts: int, lease_seconds: int, now: datetime | None = None
    ) -> bool:
        pass

    @abstractmethod
    def finalize_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        status: Literal["completed", "partial", "failed"],
        findings: list[Finding],
        analysis_meta: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
        latency_ms: int | None,
        merge_base_sha: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Fenced by `attempts`: returns False (and writes nothing durable to
        the run) if this attempt no longer holds the job. Replaces any findings
        left by an earlier crashed attempt."""

    @abstractmethod
    def requeue_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        delay_seconds: float,
        error_code: str,
        error_message: str,
        now: datetime | None = None,
    ) -> str | None:
        """Retry after a transient error. Returns the resulting status
        ("pending", or "failed" if attempts are exhausted), or None if fenced out."""

    @abstractmethod
    def supersede_review_run(
        self,
        review_run_id: str,
        attempts: int | None,
        error_code: str = "superseded",
        now: datetime | None = None,
    ) -> bool:
        pass

    @abstractmethod
    def retry_review_run(
        self, review_run_id: str, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """Manual retry: only a `failed` run goes back to `pending` (attempts reset)."""

    @abstractmethod
    def update_review_run(self, review_run_id: str, **fields: Any) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def get_review_run(self, review_run_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def list_review_runs_for_pull_request(self, pull_request_id: str) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def get_job_context(self, review_run_id: str) -> JobContext | None:
        pass

    # ------------------------------------------------------------------
    # findings / summaries
    # ------------------------------------------------------------------
    @abstractmethod
    def list_installations_summary(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def create_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        """Persist normalized findings for a run. Production code persists via
        finalize_review_run (atomic with the status change); this remains for
        tools and tests that need findings without a job lifecycle."""

    @abstractmethod
    def get_findings_for_review_run(self, review_run_id: str) -> list[dict[str, Any]]:
        pass


class InMemoryReviewStore(ReviewStore):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._deliveries: dict[str, dict[str, Any]] = {}
        self._installations: dict[str, dict[str, Any]] = {}
        self._installations_by_github_id: dict[int, str] = {}
        self._repositories: dict[str, dict[str, Any]] = {}
        self._repositories_by_github_id: dict[int, str] = {}
        self._pull_requests: dict[str, dict[str, Any]] = {}
        self._pull_requests_by_key: dict[tuple[str, int], str] = {}
        self._review_runs: dict[str, dict[str, Any]] = {}
        self._findings: dict[str, dict[str, Any]] = {}

    # --- deliveries -----------------------------------------------------
    def claim_delivery(
        self,
        delivery_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
    ) -> DeliveryClaim:
        now = now or _now()
        with self._lock:
            row = self._deliveries.get(delivery_id)
            if row is None:
                self._deliveries[delivery_id] = {
                    "delivery_id": delivery_id,
                    "event_type": event_type,
                    "status": "processing",
                    "attempts": 1,
                    "payload": payload,
                    "last_error": None,
                    "received_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                return DeliveryClaim("new", 1)

            if row["status"] == "succeeded":
                return DeliveryClaim("duplicate", row["attempts"])
            if row["status"] == "processing":
                age = now - _parse(row["updated_at"])
                if age < timedelta(seconds=lease_seconds):
                    return DeliveryClaim("in_progress", row["attempts"])

            row.update(
                status="processing",
                attempts=row["attempts"] + 1,
                payload=payload,
                updated_at=now.isoformat(),
            )
            return DeliveryClaim("reclaimed", row["attempts"])

    def mark_delivery(
        self, delivery_id: str, outcome: DeliveryOutcome, error: str | None = None
    ) -> None:
        with self._lock:
            row = self._deliveries.get(delivery_id)
            if row is None:
                return
            row.update(
                status=outcome,
                last_error=(error or "")[:500] or None,
                updated_at=_now().isoformat(),
            )

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._deliveries.get(delivery_id)
            return dict(row) if row else None

    def list_reclaimable_deliveries(
        self,
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        now = now or _now()
        cutoff = now - timedelta(seconds=lease_seconds)
        with self._lock:
            rows = [
                dict(r)
                for r in self._deliveries.values()
                if r["status"] == "retryable"
                or (r["status"] == "processing" and _parse(r["updated_at"]) < cutoff)
            ]
        rows.sort(key=lambda r: r["updated_at"])
        return rows[:limit]

    # --- installations / repositories / pull requests --------------------
    def upsert_installation(
        self,
        github_installation_id: int,
        account_login: str | None,
        account_type: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            existing_id = self._installations_by_github_id.get(github_installation_id)
            if existing_id:
                row = self._installations[existing_id]
                if account_login is not None:
                    row["account_login"] = account_login
                if account_type is not None:
                    row["account_type"] = account_type
                return dict(row)

            row = {
                "id": str(uuid.uuid4()),
                "github_installation_id": github_installation_id,
                "account_login": account_login,
                "account_type": account_type,
                "created_at": _now().isoformat(),
            }
            self._installations[row["id"]] = row
            self._installations_by_github_id[github_installation_id] = row["id"]
            return dict(row)

    def deactivate_repositories_for_installation(self, github_installation_id: int) -> int:
        with self._lock:
            installation_id = self._installations_by_github_id.get(github_installation_id)
            if not installation_id:
                return 0
            count = 0
            for repo in self._repositories.values():
                if repo["installation_id"] == installation_id and repo["is_active"]:
                    repo["is_active"] = False
                    count += 1
            return count

    def upsert_repository(
        self,
        installation_row_id: str,
        github_repo_id: int,
        full_name: str,
        default_branch: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            existing_id = self._repositories_by_github_id.get(github_repo_id)
            if existing_id:
                row = self._repositories[existing_id]
                row["full_name"] = full_name
                if default_branch is not None:
                    row["default_branch"] = default_branch
                row["updated_at"] = _now().isoformat()
                return dict(row)

            row = {
                "id": str(uuid.uuid4()),
                "installation_id": installation_row_id,
                "github_repo_id": github_repo_id,
                "full_name": full_name,
                "default_branch": default_branch,
                "is_active": True,
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            }
            self._repositories[row["id"]] = row
            self._repositories_by_github_id[github_repo_id] = row["id"]
            return dict(row)

    def set_repository_active(self, github_repo_id: int, is_active: bool) -> dict[str, Any] | None:
        with self._lock:
            existing_id = self._repositories_by_github_id.get(github_repo_id)
            if not existing_id:
                return None
            row = self._repositories[existing_id]
            row["is_active"] = is_active
            row["updated_at"] = _now().isoformat()
            return dict(row)

    def get_repository_by_github_id(self, github_repo_id: int) -> dict[str, Any] | None:
        with self._lock:
            existing_id = self._repositories_by_github_id.get(github_repo_id)
            return dict(self._repositories[existing_id]) if existing_id else None

    def upsert_pull_request(
        self,
        repository_id: str,
        github_pr_number: int,
        title: str | None,
        author_login: str | None,
        head_sha: str | None,
        base_sha: str | None,
        state: str | None,
        github_updated_at: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            key = (repository_id, github_pr_number)
            existing_id = self._pull_requests_by_key.get(key)
            if existing_id:
                row = self._pull_requests[existing_id]
                stored = _parse(row.get("github_updated_at"))
                incoming = _parse(github_updated_at)
                if stored and incoming and incoming < stored:
                    return {**row, "stale_event": True}
                row.update(
                    title=title,
                    author_login=author_login,
                    head_sha=head_sha,
                    base_sha=base_sha,
                    state=state,
                    github_updated_at=github_updated_at or row.get("github_updated_at"),
                    updated_at=_now().isoformat(),
                )
                return {**row, "stale_event": False}

            row = {
                "id": str(uuid.uuid4()),
                "repository_id": repository_id,
                "github_pr_number": github_pr_number,
                "title": title,
                "author_login": author_login,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "state": state,
                "github_updated_at": github_updated_at,
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            }
            self._pull_requests[row["id"]] = row
            self._pull_requests_by_key[key] = row["id"]
            return {**row, "stale_event": False}

    def get_pull_request(self, pull_request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._pull_requests.get(pull_request_id)
            return dict(row) if row else None

    # --- review runs = durable jobs --------------------------------------
    def enqueue_review_run(
        self,
        pull_request_id: str,
        trigger_event: str,
        head_sha: str | None,
        base_sha: str | None,
        delivery_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        now = now or _now()
        with self._lock:
            if head_sha is not None:
                for run in self._review_runs.values():
                    if run["pull_request_id"] == pull_request_id and run["head_sha"] == head_sha:
                        return dict(run), False

            row = {
                "id": str(uuid.uuid4()),
                "pull_request_id": pull_request_id,
                "trigger_event": trigger_event,
                "status": "pending",
                "base_sha": base_sha,
                "head_sha": head_sha,
                "merge_base_sha": None,
                "attempts": 0,
                "max_attempts": max_attempts,
                "available_at": now.isoformat(),
                "started_at": None,
                "completed_at": None,
                "latency_ms": None,
                "error_message": None,
                "error_code": None,
                "analysis_meta": None,
                "delivery_id": delivery_id,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            for other in self._review_runs.values():
                if (
                    other["pull_request_id"] == pull_request_id
                    and other["status"] == "pending"
                    and other["head_sha"] != head_sha
                ):
                    other.update(
                        status="superseded",
                        error_code="superseded_by_newer_head",
                        updated_at=now.isoformat(),
                    )
            self._review_runs[row["id"]] = row
            return dict(row), True

    def claim_next_review_run(
        self, lease_seconds: int, now: datetime | None = None
    ) -> dict[str, Any] | None:
        now = now or _now()
        with self._lock:
            due = [
                r
                for r in self._review_runs.values()
                if r["status"] in ("pending", "running") and _parse(r["available_at"]) <= now
            ]
            due.sort(key=lambda r: r["created_at"])
            for run in due:
                if run["status"] == "running" and run["attempts"] >= run["max_attempts"]:
                    run.update(
                        status="failed",
                        error_code="max_attempts_exceeded",
                        error_message="lease expired repeatedly; attempts exhausted",
                        completed_at=now.isoformat(),
                        updated_at=now.isoformat(),
                    )
                    continue
                run.update(
                    status="running",
                    attempts=run["attempts"] + 1,
                    started_at=now.isoformat(),
                    available_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
                    error_message=None,
                    error_code=None,
                    updated_at=now.isoformat(),
                )
                return dict(run)
            return None

    def extend_lease(
        self, review_run_id: str, attempts: int, lease_seconds: int, now: datetime | None = None
    ) -> bool:
        now = now or _now()
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run or run["status"] != "running" or run["attempts"] != attempts:
                return False
            run["available_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
            run["updated_at"] = now.isoformat()
            return True

    def finalize_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        status: Literal["completed", "partial", "failed"],
        findings: list[Finding],
        analysis_meta: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
        latency_ms: int | None,
        merge_base_sha: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        now = now or _now()
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run or run["status"] != "running" or run["attempts"] != attempts:
                return False
            stale = [k for k, v in self._findings.items() if v["review_run_id"] == review_run_id]
            for fid in stale:
                del self._findings[fid]
            self._insert_findings(review_run_id, findings)
            run.update(
                status=status,
                completed_at=now.isoformat(),
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=(error_message or "")[:1000] or None,
                analysis_meta=analysis_meta,
                merge_base_sha=merge_base_sha or run.get("merge_base_sha"),
                updated_at=now.isoformat(),
            )
            return True

    def requeue_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        delay_seconds: float,
        error_code: str,
        error_message: str,
        now: datetime | None = None,
    ) -> str | None:
        now = now or _now()
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run or run["status"] != "running" or run["attempts"] != attempts:
                return None
            if run["attempts"] >= run["max_attempts"]:
                run.update(
                    status="failed",
                    error_code=error_code,
                    error_message=error_message[:1000],
                    completed_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                return "failed"
            run.update(
                status="pending",
                available_at=(now + timedelta(seconds=delay_seconds)).isoformat(),
                error_code=error_code,
                error_message=error_message[:1000],
                updated_at=now.isoformat(),
            )
            return "pending"

    def supersede_review_run(
        self,
        review_run_id: str,
        attempts: int | None,
        error_code: str = "superseded",
        now: datetime | None = None,
    ) -> bool:
        now = now or _now()
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run:
                return False
            holds_job = run["status"] == "running" and run["attempts"] == attempts
            if not (run["status"] == "pending" or holds_job):
                return False
            run.update(
                status="superseded",
                error_code=error_code,
                completed_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            return True

    def retry_review_run(
        self, review_run_id: str, now: datetime | None = None
    ) -> dict[str, Any] | None:
        now = now or _now()
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run or run["status"] != "failed":
                return None
            run.update(
                status="pending",
                attempts=0,
                available_at=now.isoformat(),
                error_code=None,
                error_message=None,
                completed_at=None,
                updated_at=now.isoformat(),
            )
            return dict(run)

    def update_review_run(self, review_run_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            row = self._review_runs.get(review_run_id)
            if not row:
                return None
            row.update(**fields, updated_at=_now().isoformat())
            return dict(row)

    def get_review_run(self, review_run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._review_runs.get(review_run_id)
            return dict(row) if row else None

    def list_review_runs_for_pull_request(self, pull_request_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(r)
                for r in self._review_runs.values()
                if r["pull_request_id"] == pull_request_id
            ]
        rows.sort(key=lambda r: r["created_at"])
        return rows

    def get_job_context(self, review_run_id: str) -> JobContext | None:
        with self._lock:
            run = self._review_runs.get(review_run_id)
            if not run:
                return None
            pr = self._pull_requests.get(run["pull_request_id"])
            repo = self._repositories.get(pr["repository_id"]) if pr else None
            inst = self._installations.get(repo["installation_id"]) if repo else None
            if not (pr and repo and inst):
                return None
            return JobContext(dict(run), dict(pr), dict(repo), dict(inst))

    # --- findings / summaries ---------------------------------------------
    def list_installations_summary(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries = []
            for inst in self._installations.values():
                repos = [
                    r for r in self._repositories.values() if r["installation_id"] == inst["id"]
                ]
                summaries.append(
                    {
                        "account_login": inst["account_login"],
                        "account_type": inst["account_type"],
                        "github_installation_id": inst["github_installation_id"],
                        "repository_count": len(repos),
                        "repositories": [
                            {"full_name": r["full_name"], "is_active": r["is_active"]}
                            for r in repos
                        ],
                    }
                )
            return summaries

    def _insert_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        rows = []
        for f in findings:
            row = {
                "id": str(uuid.uuid4()),
                **finding_row(review_run_id, f),
                "github_comment_id": None,
                "created_at": _now().isoformat(),
            }
            self._findings[row["id"]] = row
            rows.append(dict(row))
        return rows

    def create_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        with self._lock:
            return self._insert_findings(review_run_id, findings)

    def get_findings_for_review_run(self, review_run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(row)
                for row in self._findings.values()
                if row["review_run_id"] == review_run_id
            ]


class SupabaseReviewStore(ReviewStore):
    """Real implementation backed by Supabase (PostgREST via supabase-py).

    NOT exercised against a live project in this environment — no
    credentials were available. See docs/staging-test-phase2.md. The job
    claim and finalize paths use conditional updates (compare-and-swap on
    status/attempts) so concurrent workers cannot both win; that is by
    construction, not verified against a live Postgres.
    """

    def __init__(self, url: str, service_role_key: str) -> None:
        from supabase import Client, create_client

        self._client: Client = create_client(url, service_role_key)

    # --- deliveries -----------------------------------------------------
    def claim_delivery(
        self,
        delivery_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
    ) -> DeliveryClaim:
        now = now or _now()
        try:
            self._client.table("webhook_deliveries").insert(
                {
                    "delivery_id": delivery_id,
                    "event_type": event_type,
                    "status": "processing",
                    "attempts": 1,
                    "payload": payload,
                    "expires_at": (now + timedelta(hours=24)).isoformat(),
                    "updated_at": now.isoformat(),
                }
            ).execute()
            return DeliveryClaim("new", 1)
        except Exception as exc:  # postgrest raises on unique-constraint violation
            if not _is_unique_violation(exc):
                raise

        row = self.get_delivery(delivery_id)
        if row is None:  # deleted between the two calls; treat as busy, caller retries
            return DeliveryClaim("in_progress", 0)
        if row["status"] == "succeeded":
            return DeliveryClaim("duplicate", row["attempts"])
        if row["status"] == "processing":
            age = now - _parse(row["updated_at"])
            if age < timedelta(seconds=lease_seconds):
                return DeliveryClaim("in_progress", row["attempts"])

        # Compare-and-swap on (status, attempts): only one claimant wins.
        won = (
            self._client.table("webhook_deliveries")
            .update(
                {
                    "status": "processing",
                    "attempts": row["attempts"] + 1,
                    "payload": payload,
                    "updated_at": now.isoformat(),
                }
            )
            .eq("delivery_id", delivery_id)
            .eq("status", row["status"])
            .eq("attempts", row["attempts"])
            .execute()
        )
        if won.data:
            return DeliveryClaim("reclaimed", row["attempts"] + 1)
        return DeliveryClaim("in_progress", row["attempts"])

    def mark_delivery(
        self, delivery_id: str, outcome: DeliveryOutcome, error: str | None = None
    ) -> None:
        self._client.table("webhook_deliveries").update(
            {
                "status": outcome,
                "last_error": (error or "")[:500] or None,
                "updated_at": _now().isoformat(),
            }
        ).eq("delivery_id", delivery_id).execute()

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("webhook_deliveries")
            .select("*")
            .eq("delivery_id", delivery_id)
            .maybe_single()
            .execute()
        )
        return result.data if result else None

    def list_reclaimable_deliveries(
        self,
        now: datetime | None = None,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        now = now or _now()
        cutoff = (now - timedelta(seconds=lease_seconds)).isoformat()
        table = self._client.table("webhook_deliveries")
        retryable = table.select("*").eq("status", "retryable").limit(limit).execute().data
        stale = (
            self._client.table("webhook_deliveries")
            .select("*")
            .eq("status", "processing")
            .lt("updated_at", cutoff)
            .limit(limit)
            .execute()
            .data
        )
        rows = sorted(retryable + stale, key=lambda r: r["updated_at"])
        return rows[:limit]

    # --- installations / repositories / pull requests --------------------
    def upsert_installation(
        self,
        github_installation_id: int,
        account_login: str | None,
        account_type: str | None,
    ) -> dict[str, Any]:
        existing = (
            self._client.table("installations")
            .select("*")
            .eq("github_installation_id", github_installation_id)
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            updates: dict[str, Any] = {}
            if account_login is not None:
                updates["account_login"] = account_login
            if account_type is not None:
                updates["account_type"] = account_type
            if updates:
                result = (
                    self._client.table("installations")
                    .update(updates)
                    .eq("id", existing.data["id"])
                    .execute()
                )
                return result.data[0]
            return existing.data

        result = (
            self._client.table("installations")
            .insert(
                {
                    "github_installation_id": github_installation_id,
                    "account_login": account_login,
                    "account_type": account_type,
                }
            )
            .execute()
        )
        return result.data[0]

    def deactivate_repositories_for_installation(self, github_installation_id: int) -> int:
        installation = (
            self._client.table("installations")
            .select("id")
            .eq("github_installation_id", github_installation_id)
            .maybe_single()
            .execute()
        )
        if not installation or not installation.data:
            return 0
        result = (
            self._client.table("repositories")
            .update({"is_active": False})
            .eq("installation_id", installation.data["id"])
            .eq("is_active", True)
            .execute()
        )
        return len(result.data)

    def upsert_repository(
        self,
        installation_row_id: str,
        github_repo_id: int,
        full_name: str,
        default_branch: str | None,
    ) -> dict[str, Any]:
        existing = (
            self._client.table("repositories")
            .select("*")
            .eq("github_repo_id", github_repo_id)
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            updates: dict[str, Any] = {"full_name": full_name}
            if default_branch is not None:
                updates["default_branch"] = default_branch
            result = (
                self._client.table("repositories")
                .update(updates)
                .eq("id", existing.data["id"])
                .execute()
            )
            return result.data[0]

        result = (
            self._client.table("repositories")
            .insert(
                {
                    "installation_id": installation_row_id,
                    "github_repo_id": github_repo_id,
                    "full_name": full_name,
                    "default_branch": default_branch,
                    "is_active": True,
                }
            )
            .execute()
        )
        return result.data[0]

    def set_repository_active(self, github_repo_id: int, is_active: bool) -> dict[str, Any] | None:
        result = (
            self._client.table("repositories")
            .update({"is_active": is_active})
            .eq("github_repo_id", github_repo_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_repository_by_github_id(self, github_repo_id: int) -> dict[str, Any] | None:
        result = (
            self._client.table("repositories")
            .select("*")
            .eq("github_repo_id", github_repo_id)
            .maybe_single()
            .execute()
        )
        return result.data if result else None

    def upsert_pull_request(
        self,
        repository_id: str,
        github_pr_number: int,
        title: str | None,
        author_login: str | None,
        head_sha: str | None,
        base_sha: str | None,
        state: str | None,
        github_updated_at: str | None = None,
    ) -> dict[str, Any]:
        existing = (
            self._client.table("pull_requests")
            .select("*")
            .eq("repository_id", repository_id)
            .eq("github_pr_number", github_pr_number)
            .maybe_single()
            .execute()
        )
        fields: dict[str, Any] = {
            "title": title,
            "author_login": author_login,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "state": state,
        }
        if github_updated_at:
            fields["github_updated_at"] = github_updated_at

        if existing and existing.data:
            stored = _parse(existing.data.get("github_updated_at"))
            incoming = _parse(github_updated_at)
            if stored and incoming and incoming < stored:
                return {**existing.data, "stale_event": True}
            result = (
                self._client.table("pull_requests")
                .update(fields)
                .eq("id", existing.data["id"])
                .execute()
            )
            return {**result.data[0], "stale_event": False}

        result = (
            self._client.table("pull_requests")
            .insert(
                {"repository_id": repository_id, "github_pr_number": github_pr_number, **fields}
            )
            .execute()
        )
        return {**result.data[0], "stale_event": False}

    def get_pull_request(self, pull_request_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("pull_requests")
            .select("*")
            .eq("id", pull_request_id)
            .maybe_single()
            .execute()
        )
        return result.data if result else None

    # --- review runs = durable jobs --------------------------------------
    def _run_by_head(self, pull_request_id: str, head_sha: str) -> dict[str, Any] | None:
        result = (
            self._client.table("review_runs")
            .select("*")
            .eq("pull_request_id", pull_request_id)
            .eq("head_sha", head_sha)
            .maybe_single()
            .execute()
        )
        return result.data if result else None

    def enqueue_review_run(
        self,
        pull_request_id: str,
        trigger_event: str,
        head_sha: str | None,
        base_sha: str | None,
        delivery_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        now = now or _now()
        if head_sha is not None:
            existing = self._run_by_head(pull_request_id, head_sha)
            if existing:
                return existing, False

        try:
            result = (
                self._client.table("review_runs")
                .insert(
                    {
                        "pull_request_id": pull_request_id,
                        "trigger_event": trigger_event,
                        "status": "pending",
                        "head_sha": head_sha,
                        "base_sha": base_sha,
                        "max_attempts": max_attempts,
                        "available_at": now.isoformat(),
                        "delivery_id": delivery_id,
                    }
                )
                .execute()
            )
        except Exception as exc:
            if head_sha is not None and _is_unique_violation(exc):
                existing = self._run_by_head(pull_request_id, head_sha)
                if existing:
                    return existing, False
            raise

        row = result.data[0]
        if head_sha is not None:
            (
                self._client.table("review_runs")
                .update({"status": "superseded", "error_code": "superseded_by_newer_head"})
                .eq("pull_request_id", pull_request_id)
                .eq("status", "pending")
                .neq("head_sha", head_sha)
                .execute()
            )
        return row, True

    def claim_next_review_run(
        self, lease_seconds: int, now: datetime | None = None
    ) -> dict[str, Any] | None:
        now = now or _now()
        now_iso = now.isoformat()
        lease_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
        table = "review_runs"

        pending = (
            self._client.table(table)
            .select("id,status,attempts,max_attempts,created_at")
            .eq("status", "pending")
            .lte("available_at", now_iso)
            .order("created_at")
            .limit(5)
            .execute()
            .data
        )
        expired = (
            self._client.table(table)
            .select("id,status,attempts,max_attempts,created_at")
            .eq("status", "running")
            .lte("available_at", now_iso)
            .order("created_at")
            .limit(5)
            .execute()
            .data
        )
        for candidate in sorted(pending + expired, key=lambda r: r["created_at"]):
            exhausted = candidate["attempts"] >= candidate["max_attempts"]
            if candidate["status"] == "running" and exhausted:
                (
                    self._client.table(table)
                    .update(
                        {
                            "status": "failed",
                            "error_code": "max_attempts_exceeded",
                            "error_message": "lease expired repeatedly; attempts exhausted",
                            "completed_at": now_iso,
                        }
                    )
                    .eq("id", candidate["id"])
                    .eq("status", "running")
                    .eq("attempts", candidate["attempts"])
                    .execute()
                )
                continue

            won = (
                self._client.table(table)
                .update(
                    {
                        "status": "running",
                        "attempts": candidate["attempts"] + 1,
                        "started_at": now_iso,
                        "available_at": lease_iso,
                        "error_code": None,
                        "error_message": None,
                    }
                )
                .eq("id", candidate["id"])
                .eq("status", candidate["status"])
                .eq("attempts", candidate["attempts"])
                .execute()
            )
            if won.data:
                return won.data[0]
        return None

    def extend_lease(
        self, review_run_id: str, attempts: int, lease_seconds: int, now: datetime | None = None
    ) -> bool:
        now = now or _now()
        result = (
            self._client.table("review_runs")
            .update({"available_at": (now + timedelta(seconds=lease_seconds)).isoformat()})
            .eq("id", review_run_id)
            .eq("status", "running")
            .eq("attempts", attempts)
            .execute()
        )
        return bool(result.data)

    def finalize_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        status: Literal["completed", "partial", "failed"],
        findings: list[Finding],
        analysis_meta: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
        latency_ms: int | None,
        merge_base_sha: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        now = now or _now()
        # 1) Verify this attempt still holds the job before touching findings.
        held = (
            self._client.table("review_runs")
            .select("id")
            .eq("id", review_run_id)
            .eq("status", "running")
            .eq("attempts", attempts)
            .execute()
        )
        if not held.data:
            return False

        # 2) Replace findings from any earlier crashed attempt, then insert.
        self._client.table("findings").delete().eq("review_run_id", review_run_id).execute()
        if findings:
            self._client.table("findings").insert(
                [finding_row(review_run_id, f) for f in findings]
            ).execute()

        # 3) The fenced status flip is the commit point. If it loses the race
        #    (lease expired between 1 and 3 and another worker took over),
        #    the newer attempt's finalize will replace these findings.
        update: dict[str, Any] = {
            "status": status,
            "completed_at": now.isoformat(),
            "latency_ms": latency_ms,
            "error_code": error_code,
            "error_message": (error_message or "")[:1000] or None,
            "analysis_meta": analysis_meta,
        }
        if merge_base_sha:
            update["merge_base_sha"] = merge_base_sha
        done = (
            self._client.table("review_runs")
            .update(update)
            .eq("id", review_run_id)
            .eq("status", "running")
            .eq("attempts", attempts)
            .execute()
        )
        return bool(done.data)

    def requeue_review_run(
        self,
        review_run_id: str,
        attempts: int,
        *,
        delay_seconds: float,
        error_code: str,
        error_message: str,
        now: datetime | None = None,
    ) -> str | None:
        now = now or _now()
        run = self.get_review_run(review_run_id)
        if not run or run["status"] != "running" or run["attempts"] != attempts:
            return None
        exhausted = run["attempts"] >= run["max_attempts"]
        update: dict[str, Any] = {
            "status": "failed" if exhausted else "pending",
            "error_code": error_code,
            "error_message": error_message[:1000],
        }
        if exhausted:
            update["completed_at"] = now.isoformat()
        else:
            update["available_at"] = (now + timedelta(seconds=delay_seconds)).isoformat()
        done = (
            self._client.table("review_runs")
            .update(update)
            .eq("id", review_run_id)
            .eq("status", "running")
            .eq("attempts", attempts)
            .execute()
        )
        return update["status"] if done.data else None

    def supersede_review_run(
        self,
        review_run_id: str,
        attempts: int | None,
        error_code: str = "superseded",
        now: datetime | None = None,
    ) -> bool:
        now = now or _now()
        update = {"status": "superseded", "error_code": error_code, "completed_at": now.isoformat()}
        query = self._client.table("review_runs").update(update).eq("id", review_run_id)
        if attempts is None:
            query = query.eq("status", "pending")
        else:
            query = query.eq("status", "running").eq("attempts", attempts)
        return bool(query.execute().data)

    def retry_review_run(
        self, review_run_id: str, now: datetime | None = None
    ) -> dict[str, Any] | None:
        now = now or _now()
        result = (
            self._client.table("review_runs")
            .update(
                {
                    "status": "pending",
                    "attempts": 0,
                    "available_at": now.isoformat(),
                    "error_code": None,
                    "error_message": None,
                    "completed_at": None,
                }
            )
            .eq("id", review_run_id)
            .eq("status", "failed")
            .execute()
        )
        return result.data[0] if result.data else None

    def update_review_run(self, review_run_id: str, **fields: Any) -> dict[str, Any] | None:
        result = (
            self._client.table("review_runs").update(fields).eq("id", review_run_id).execute()
        )
        return result.data[0] if result.data else None

    def get_review_run(self, review_run_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("review_runs")
            .select("*")
            .eq("id", review_run_id)
            .maybe_single()
            .execute()
        )
        return result.data if result else None

    def list_review_runs_for_pull_request(self, pull_request_id: str) -> list[dict[str, Any]]:
        return (
            self._client.table("review_runs")
            .select("*")
            .eq("pull_request_id", pull_request_id)
            .order("created_at")
            .execute()
            .data
        )

    def get_job_context(self, review_run_id: str) -> JobContext | None:
        run = self.get_review_run(review_run_id)
        if not run:
            return None
        pr = self.get_pull_request(run["pull_request_id"])
        if not pr:
            return None
        repo = (
            self._client.table("repositories")
            .select("*")
            .eq("id", pr["repository_id"])
            .maybe_single()
            .execute()
        )
        if not repo or not repo.data:
            return None
        inst = (
            self._client.table("installations")
            .select("*")
            .eq("id", repo.data["installation_id"])
            .maybe_single()
            .execute()
        )
        if not inst or not inst.data:
            return None
        return JobContext(run, pr, repo.data, inst.data)

    # --- findings / summaries ---------------------------------------------
    def list_installations_summary(self) -> list[dict[str, Any]]:
        installations = self._client.table("installations").select("*").execute().data
        repositories = self._client.table("repositories").select("*").execute().data
        summaries = []
        for inst in installations:
            repos = [r for r in repositories if r["installation_id"] == inst["id"]]
            summaries.append(
                {
                    "account_login": inst["account_login"],
                    "account_type": inst["account_type"],
                    "github_installation_id": inst["github_installation_id"],
                    "repository_count": len(repos),
                    "repositories": [
                        {"full_name": r["full_name"], "is_active": r["is_active"]} for r in repos
                    ],
                }
            )
        return summaries

    def create_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        if not findings:
            return []
        rows = [finding_row(review_run_id, f) for f in findings]
        result = self._client.table("findings").insert(rows).execute()
        return result.data

    def get_findings_for_review_run(self, review_run_id: str) -> list[dict[str, Any]]:
        result = (
            self._client.table("findings")
            .select("*")
            .eq("review_run_id", review_run_id)
            .execute()
        )
        return result.data


def _is_unique_violation(exc: Exception) -> bool:
    # postgrest-py surfaces Postgres errors with a `code` attribute/dict
    # matching the SQLSTATE. 23505 = unique_violation.
    message = str(exc)
    return "23505" in message or "duplicate key value" in message


_singleton: ReviewStore | None = None
_singleton_lock = threading.Lock()


def get_store() -> ReviewStore:
    """FastAPI dependency. Cached for the process lifetime.

    Fails closed: outside `development`/`test`, a missing Supabase
    configuration raises StoreConfigurationError instead of silently falling
    back to volatile in-memory state (which would lose every event and job on
    the next restart while looking healthy).
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    with _singleton_lock:
        if _singleton is not None:
            return _singleton

        from app.config import get_settings

        settings = get_settings()
        if settings.supabase_url and settings.supabase_service_role_key:
            logger.info("store_backend=supabase")
            _singleton = SupabaseReviewStore(
                settings.supabase_url, settings.supabase_service_role_key
            )
        elif settings.in_memory_store_allowed:
            logger.warning(
                "store_backend=in_memory reason=supabase_not_configured "
                "environment=%s data_will_not_persist_across_restarts",
                settings.environment,
            )
            _singleton = InMemoryReviewStore()
        else:
            raise StoreConfigurationError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required when "
                f"ENVIRONMENT={settings.environment!r}; the in-memory store is only "
                "allowed in development/test"
            )
        return _singleton


def reset_store_singleton_for_tests() -> None:
    global _singleton
    _singleton = None
