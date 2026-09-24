"""Data access layer for Phase 2 bookkeeping.

Two implementations share one interface:

- `InMemoryReviewStore` — a process-local dict-backed store. Used by the
  test suite (no live Supabase project needed to test business logic) *and*
  as an explicit local-dev fallback when SUPABASE_URL /
  SUPABASE_SERVICE_ROLE_KEY aren't set, so `uvicorn app.main:app` still runs
  end-to-end on a laptop with nothing provisioned yet. It is never used
  automatically outside of that: get_store() logs a loud warning whenever it
  falls back to this, precisely so nobody mistakes a demo for persistence.

- `SupabaseReviewStore` — the real implementation, backed by the tables in
  supabase/migrations/0002_github_app_bookkeeping.sql. This has NOT been
  exercised against a live Supabase project in development (no credentials
  were available) — see docs/staging-test-phase2.md for the manual
  verification procedure a team member with Supabase access must run.

Both are intentionally synchronous. The Supabase Python client is
synchronous, and Phase 2's request volume is far below where blocking the
event loop during a DB round trip matters. Revisit if/when traffic (Phase 5+)
makes that a real bottleneck.
"""

from __future__ import annotations

import logging
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from analysis.finding import Finding

logger = logging.getLogger("codentry.ai_review.store")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewStore(ABC):
    @abstractmethod
    def record_delivery(self, delivery_id: str, event_type: str) -> bool:
        """Return True if this delivery_id is new, False if it's a duplicate."""

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
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    def create_review_run(self, pull_request_id: str, trigger_event: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def update_review_run(self, review_run_id: str, **fields: Any) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def get_review_run(self, review_run_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def list_installations_summary(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def create_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        """Persist normalized findings (Phase 3: ESLINT/SEMGREP; Phase 4
        onward: AI too) for a review run. Returns the stored rows, each with
        a generated id/created_at and github_comment_id left null (that's
        populated in Phase 5 once a comment is actually posted)."""

    @abstractmethod
    def get_findings_for_review_run(self, review_run_id: str) -> list[dict[str, Any]]:
        pass


class InMemoryReviewStore(ReviewStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deliveries: set[str] = set()
        self._installations: dict[str, dict[str, Any]] = {}
        self._installations_by_github_id: dict[int, str] = {}
        self._repositories: dict[str, dict[str, Any]] = {}
        self._repositories_by_github_id: dict[int, str] = {}
        self._pull_requests: dict[str, dict[str, Any]] = {}
        self._pull_requests_by_key: dict[tuple[str, int], str] = {}
        self._review_runs: dict[str, dict[str, Any]] = {}
        self._findings: dict[str, dict[str, Any]] = {}

    def record_delivery(self, delivery_id: str, event_type: str) -> bool:
        with self._lock:
            if delivery_id in self._deliveries:
                return False
            self._deliveries.add(delivery_id)
            return True

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
    ) -> dict[str, Any]:
        with self._lock:
            key = (repository_id, github_pr_number)
            existing_id = self._pull_requests_by_key.get(key)
            if existing_id:
                row = self._pull_requests[existing_id]
                row.update(
                    title=title,
                    author_login=author_login,
                    head_sha=head_sha,
                    base_sha=base_sha,
                    state=state,
                    updated_at=_now().isoformat(),
                )
                return dict(row)

            row = {
                "id": str(uuid.uuid4()),
                "repository_id": repository_id,
                "github_pr_number": github_pr_number,
                "title": title,
                "author_login": author_login,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "state": state,
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            }
            self._pull_requests[row["id"]] = row
            self._pull_requests_by_key[key] = row["id"]
            return dict(row)

    def create_review_run(self, pull_request_id: str, trigger_event: str) -> dict[str, Any]:
        with self._lock:
            row = {
                "id": str(uuid.uuid4()),
                "pull_request_id": pull_request_id,
                "trigger_event": trigger_event,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "latency_ms": None,
                "error_message": None,
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            }
            self._review_runs[row["id"]] = row
            return dict(row)

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

    def create_findings(self, review_run_id: str, findings: list[Finding]) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for f in findings:
                row = {
                    "id": str(uuid.uuid4()),
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
                    "github_comment_id": None,
                    "dedup_hash": f.dedup_hash,
                    "created_at": _now().isoformat(),
                }
                self._findings[row["id"]] = row
                rows.append(dict(row))
            return rows

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
    credentials were available. See docs/staging-test-phase2.md.
    """

    def __init__(self, url: str, service_role_key: str) -> None:
        from supabase import Client, create_client

        self._client: Client = create_client(url, service_role_key)

    def record_delivery(self, delivery_id: str, event_type: str) -> bool:
        expires_at = (_now() + timedelta(hours=24)).isoformat()
        try:
            self._client.table("webhook_deliveries").insert(
                {
                    "delivery_id": delivery_id,
                    "event_type": event_type,
                    "expires_at": expires_at,
                }
            ).execute()
            return True
        except Exception as exc:  # postgrest raises on unique-constraint violation
            if _is_unique_violation(exc):
                return False
            raise

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
    ) -> dict[str, Any]:
        existing = (
            self._client.table("pull_requests")
            .select("*")
            .eq("repository_id", repository_id)
            .eq("github_pr_number", github_pr_number)
            .maybe_single()
            .execute()
        )
        fields = {
            "title": title,
            "author_login": author_login,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "state": state,
        }
        if existing and existing.data:
            result = (
                self._client.table("pull_requests")
                .update(fields)
                .eq("id", existing.data["id"])
                .execute()
            )
            return result.data[0]

        result = (
            self._client.table("pull_requests")
            .insert(
                {
                    "repository_id": repository_id,
                    "github_pr_number": github_pr_number,
                    **fields,
                }
            )
            .execute()
        )
        return result.data[0]

    def create_review_run(self, pull_request_id: str, trigger_event: str) -> dict[str, Any]:
        result = (
            self._client.table("review_runs")
            .insert(
                {
                    "pull_request_id": pull_request_id,
                    "trigger_event": trigger_event,
                    "status": "pending",
                }
            )
            .execute()
        )
        return result.data[0]

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
        rows = [
            {
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
            }
            for f in findings
        ]
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

    Falls back to InMemoryReviewStore with a loud warning if Supabase isn't
    configured, so local development and CI work without a provisioned
    project — see the module docstring.
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
        else:
            logger.warning(
                "store_backend=in_memory reason=supabase_not_configured "
                "data_will_not_persist_across_restarts"
            )
            _singleton = InMemoryReviewStore()
        return _singleton


def reset_store_singleton_for_tests() -> None:
    global _singleton
    _singleton = None
