"""Phase 3 review execution: pending -> running -> completed/failed, with
real ESLint + Semgrep findings persisted in between. No Claude, no RAG — see
analysis/static_analysis.py for what actually runs.

Deliberately a plain (synchronous) function, not `async def`: FastAPI's
BackgroundTasks runs sync callables in a worker thread (via
starlette.concurrency.run_in_threadpool) rather than on the main event loop,
which matters here because ESLint/Semgrep subprocess calls block for real
wall-clock time (up to 30s each). An async version would block the event
loop — and therefore every other concurrent webhook request — for the
duration of a single review. Bridging back into async for the GitHub fetch
(`asyncio.run(...)`) is safe specifically because we're already off the main
loop, in our own worker thread.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from analysis.changed_files import ChangedFilesError, fetch_changed_files
from analysis.static_analysis import analyze_source_files
from app.config import get_settings
from app.store import ReviewStore

logger = logging.getLogger("codentry.ai_review.review_runner")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_placeholder_review(store: ReviewStore, review_run_id: str) -> None:
    """Retained for tests/tools that want the pure "prove the async
    lifecycle" behavior without touching GitHub — no longer wired into the
    production webhook path, which now uses run_static_review below."""
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
            store.update_review_run(review_run_id, status="failed", error_message=str(exc)[:500])
        except Exception:
            logger.exception("review_run_failure_not_recorded review_run_id=%s", review_run_id)


def run_static_review(
    store: ReviewStore,
    review_run_id: str,
    github_installation_id: int,
    repo_full_name: str,
    github_pr_number: int,
) -> None:
    """The real Phase 3 pipeline: fetch changed files from GitHub, run
    ESLint + Semgrep, persist normalized findings, and land on a terminal
    status that honestly reflects what happened — see
    analysis.static_analysis.StaticAnalysisResult.overall_status for the
    completed / partial_failure / failed distinction this maps from.
    """
    started_at = _now()
    try:
        store.update_review_run(review_run_id, status="running", started_at=started_at.isoformat())
    except Exception:
        logger.exception("review_run_start_failed review_run_id=%s", review_run_id)
        return

    logger.info(
        "review_run_started review_run_id=%s repo=%s pr=%d",
        review_run_id,
        repo_full_name,
        github_pr_number,
    )

    settings = get_settings()
    if not settings.github_app_id or not settings.github_private_key:
        _finish(
            store,
            review_run_id,
            started_at,
            status="failed",
            findings_count=0,
            error_message="github_app_not_configured: GITHUB_APP_ID/GITHUB_PRIVATE_KEY unset",
        )
        return

    try:
        source_files = asyncio.run(
            fetch_changed_files(
                app_id=settings.github_app_id,
                private_key_pem=settings.github_private_key,
                github_installation_id=github_installation_id,
                repo_full_name=repo_full_name,
                pr_number=github_pr_number,
            )
        )
    except ChangedFilesError as exc:
        _finish(
            store,
            review_run_id,
            started_at,
            status="failed",
            findings_count=0,
            error_message=f"changed_files_fetch_failed: {exc}",
        )
        return

    result = analyze_source_files(source_files)

    if result.findings:
        store.create_findings(review_run_id, result.findings)

    db_status = "failed" if result.overall_status == "failed" else "completed"
    _finish(
        store,
        review_run_id,
        started_at,
        status=db_status,
        findings_count=len(result.findings),
        error_message=result.error_summary,
    )


def _finish(
    store: ReviewStore,
    review_run_id: str,
    started_at: datetime,
    *,
    status: str,
    findings_count: int,
    error_message: str | None,
) -> None:
    try:
        completed_at = _now()
        latency_ms = int((completed_at - started_at).total_seconds() * 1000)
        store.update_review_run(
            review_run_id,
            status=status,
            completed_at=completed_at.isoformat(),
            latency_ms=latency_ms,
            error_message=error_message,
        )
        logger.info(
            "review_run_%s review_run_id=%s latency_ms=%d findings=%d error=%s",
            status,
            review_run_id,
            latency_ms,
            findings_count,
            error_message,
        )
    except Exception as exc:
        logger.exception("review_run_failed review_run_id=%s", review_run_id)
        try:
            store.update_review_run(review_run_id, status="failed", error_message=str(exc)[:500])
        except Exception:
            logger.exception("review_run_failure_not_recorded review_run_id=%s", review_run_id)
