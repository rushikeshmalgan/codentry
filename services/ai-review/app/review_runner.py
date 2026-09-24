"""Executes one claimed review job: pinned snapshot -> differential static
analysis -> fenced finalize. No Claude, no RAG, no AI of any kind (Phase 0).

    claimed job (review_runs row, status=running, attempts=N)
        |
        |  1. still the PR's current head?   no -> superseded
        |  2. pinned, paginated snapshot     head moved -> superseded
        |                                    transient  -> requeue w/ backoff
        |                                    permanent  -> failed (error_code)
        |  3. analyze BASE (merge base) and HEAD with identical tools/rules
        |     and the SAME trusted config (never the PR's own)
        |  4. classify: new / existing (moved?) / fixed
        |  5. finalize (fenced by attempts): findings + status + analysis_meta
        v
    completed | partial | failed | superseded

"completed" means: every tool ran, nothing that should have been analyzed
was skipped, and the differential covered every file. Anything less is
"partial" with the reasons recorded in analysis_meta — never a silent
"completed". Only `new` findings are ever candidates for being reported on a
PR (Phase 5); `existing` and `fixed` are recorded for evaluation.

The function is synchronous by design: it runs on the worker thread, where
blocking on ESLint/Semgrep subprocesses is fine, and bridges to async only
for the GitHub fetch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from analysis.changed_files import (
    HeadMovedError,
    PullRequestSnapshot,
    SnapshotError,
    fetch_pull_request_snapshot,
)
from analysis.redact import redact_secrets
from analysis.snapshot_analysis import AnalysisOutcome, analyze_pull_request_snapshot
from analysis.static_analysis import StaticAnalysisResult
from app.config import Settings, get_settings
from app.store import JobContext, ReviewStore

logger = logging.getLogger("codentry.ai_review.review_runner")

MAX_BACKOFF_SECONDS = 900.0
BASE_BACKOFF_SECONDS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempts: int, retry_after: float | None = None) -> float:
    """Exponential backoff (30s, 60s, 120s, ...), honoring a server Retry-After."""
    computed = min(BASE_BACKOFF_SECONDS * (2 ** max(attempts - 1, 0)), MAX_BACKOFF_SECONDS)
    return max(computed, retry_after or 0.0)


def execute_review_run(
    store: ReviewStore,
    run: dict[str, Any],
    settings: Settings | None = None,
    fetcher=fetch_pull_request_snapshot,
) -> str:
    """Runs one claimed job and returns its resulting status. Never raises:
    an unexpected exception requeues the job (or fails it once attempts are
    exhausted); if even that cannot be recorded, the lease expiry recovers it."""
    settings = settings or get_settings()
    run_id, attempts = run["id"], run["attempts"]
    started = _now()

    try:
        return _execute(store, run, settings, fetcher, started)
    except Exception as exc:
        logger.exception("review_run_unexpected_error review_run_id=%s", run_id)
        try:
            outcome = store.requeue_review_run(
                run_id,
                attempts,
                delay_seconds=backoff_seconds(attempts),
                error_code="internal_error",
                error_message=redact_secrets(f"{type(exc).__name__}: {exc}") or "internal_error",
            )
            return outcome or "fenced_out"
        except Exception:
            logger.exception("review_run_requeue_failed review_run_id=%s", run_id)
            return "unrecorded"


def _execute(
    store: ReviewStore,
    run: dict[str, Any],
    settings: Settings,
    fetcher,
    started: datetime,
) -> str:
    run_id, attempts = run["id"], run["attempts"]

    ctx = store.get_job_context(run_id)
    if ctx is None:
        return _finalize_failed(
            store,
            run,
            started,
            "job_context_missing",
            "pull request, repository or installation row missing",
        )

    early = _preflight(store, ctx, run)
    if early:
        return early

    if not settings.github_app_id or not settings.github_private_key:
        return _finalize_failed(
            store,
            run,
            started,
            "github_app_not_configured",
            "GITHUB_APP_ID/GITHUB_PRIVATE_KEY unset",
        )

    logger.info(
        "review_run_started review_run_id=%s repo=%s pr=%d head=%s attempt=%d",
        run_id,
        ctx.repository["full_name"],
        ctx.pull_request["github_pr_number"],
        (run["head_sha"] or "")[:12],
        attempts,
    )

    try:
        snapshot = asyncio.run(
            fetcher(
                app_id=settings.github_app_id,
                private_key_pem=settings.github_private_key,
                github_installation_id=ctx.installation["github_installation_id"],
                repo_full_name=ctx.repository["full_name"],
                pr_number=ctx.pull_request["github_pr_number"],
                expected_head_sha=run["head_sha"],
                base_sha=run["base_sha"],
            )
        )
    except HeadMovedError as exc:
        store.supersede_review_run(run_id, attempts, "superseded_by_newer_head")
        logger.info("review_run_superseded review_run_id=%s reason=%s", run_id, exc)
        return "superseded"
    except SnapshotError as exc:
        return _handle_snapshot_error(store, run, started, exc)

    store.extend_lease(run_id, attempts, settings.job_lease_seconds)

    outcome = analyze_snapshot(snapshot, ctx)
    store.extend_lease(run_id, attempts, settings.job_lease_seconds)

    # Last check before committing: the PR head must still be this run's head.
    current = store.get_pull_request(ctx.pull_request["id"])
    if current and current.get("head_sha") and current["head_sha"] != run["head_sha"]:
        store.supersede_review_run(run_id, attempts, "superseded_by_newer_head")
        return "superseded"

    latency_ms = int((_now() - started).total_seconds() * 1000)
    committed = store.finalize_review_run(
        run_id,
        attempts,
        status=outcome.status,
        findings=outcome.findings,
        analysis_meta=outcome.meta,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        latency_ms=latency_ms,
        merge_base_sha=snapshot.merge_base_sha,
    )
    if not committed:
        logger.warning(
            "review_run_finalize_fenced_out review_run_id=%s attempt=%d", run_id, attempts
        )
        return "fenced_out"

    logger.info(
        "review_run_%s review_run_id=%s latency_ms=%d findings=%d new=%d error_code=%s",
        outcome.status,
        run_id,
        latency_ms,
        len(outcome.findings),
        outcome.meta["differential"]["new"],
        outcome.error_code,
    )
    return outcome.status


def _preflight(store: ReviewStore, ctx: JobContext, run: dict[str, Any]) -> str | None:
    run_id, attempts = run["id"], run["attempts"]
    if not ctx.repository["is_active"]:
        store.supersede_review_run(run_id, attempts, "repository_inactive")
        return "superseded"
    stored_head = ctx.pull_request.get("head_sha")
    if stored_head and run["head_sha"] and stored_head != run["head_sha"]:
        store.supersede_review_run(run_id, attempts, "superseded_by_newer_head")
        return "superseded"
    return None


def _handle_snapshot_error(
    store: ReviewStore, run: dict[str, Any], started: datetime, exc: SnapshotError
) -> str:
    run_id, attempts = run["id"], run["attempts"]
    message = redact_secrets(str(exc)) or exc.kind
    if exc.retryable:
        outcome = store.requeue_review_run(
            run_id,
            attempts,
            delay_seconds=backoff_seconds(attempts, exc.retry_after),
            error_code=exc.kind,
            error_message=message,
        )
        logger.warning(
            "review_run_requeued review_run_id=%s kind=%s result=%s", run_id, exc.kind, outcome
        )
        return outcome or "fenced_out"
    return _finalize_failed(store, run, started, exc.kind, message)


def _finalize_failed(
    store: ReviewStore, run: dict[str, Any], started: datetime, code: str, message: str
) -> str:
    latency_ms = int((_now() - started).total_seconds() * 1000)
    store.finalize_review_run(
        run["id"],
        run["attempts"],
        status="failed",
        findings=[],
        analysis_meta=None,
        error_code=code,
        error_message=redact_secrets(message),
        latency_ms=latency_ms,
    )
    logger.warning("review_run_failed review_run_id=%s error_code=%s", run["id"], code)
    return "failed"


# ---------------------------------------------------------------------------
# Snapshot analysis. The pure implementation lives in analysis/snapshot_analysis.py
# so the evaluation harness runs exactly the same code as the worker.
# ---------------------------------------------------------------------------
def analyze_snapshot(snapshot: PullRequestSnapshot, ctx: JobContext) -> AnalysisOutcome:
    return analyze_pull_request_snapshot(snapshot, f"repo:{ctx.repository['github_repo_id']}")


__all__ = ["execute_review_run", "analyze_snapshot", "backoff_seconds", "StaticAnalysisResult"]
