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
from analysis.diff import FileDiff, build_file_diff
from analysis.differential import classify
from analysis.finding import Finding
from analysis.redact import redact_secrets
from analysis.static_analysis import StaticAnalysisResult, analyze_source_files
from analysis.trusted_config import TRUSTED_CONFIG_FILENAME, sanitize_overlay
from analysis.workspace import is_incomplete_skip
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
# Snapshot analysis (pure: no store, no network — directly testable)
# ---------------------------------------------------------------------------
class AnalysisOutcome:
    def __init__(
        self,
        status: str,
        findings: list[Finding],
        meta: dict[str, Any],
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        self.status = status
        self.findings = findings
        self.meta = meta
        self.error_code = error_code
        self.error_message = error_message


def _tool_ok(status: str) -> bool:
    return status in ("ok", "skipped")


def analyze_snapshot(snapshot: PullRequestSnapshot, ctx: JobContext) -> AnalysisOutcome:
    overlay = None
    if snapshot.trusted_config_text is not None:
        overlay = sanitize_overlay(
            snapshot.trusted_config_text,
            source_ref=f"{snapshot.base_sha}:{TRUSTED_CONFIG_FILENAME}",
        )
    scope = f"repo:{ctx.repository['github_repo_id']}"
    rename_map = snapshot.rename_map

    head_result = analyze_source_files(snapshot.head_files, overlay, scope)
    base_result = analyze_source_files(snapshot.base_files, overlay, scope, rename_map)

    diffs: dict[str, FileDiff] = {
        f.path: build_file_diff(
            f.patch, f.base.content if f.base else None, f.head.content if f.head else None
        )
        for f in snapshot.files
    }

    # Which head findings can be honestly classified against the base?
    # A tool that failed on the base, or a file whose old content could not be
    # read, gives no basis for "new vs pre-existing" — those stay unclassified
    # (change_status=None) and are never treated as new.
    base_ok_sources = set()
    if _tool_ok(base_result.eslint_status):
        base_ok_sources.add("ESLINT")
    if _tool_ok(base_result.semgrep_status):
        base_ok_sources.add("SEMGREP")
    base_unavailable_paths = {f.path for f in snapshot.files if f.base_unavailable}
    for entry in base_result.skipped_files:
        if not is_incomplete_skip(entry):
            continue
        if entry["path"] == "*":  # base findings were truncated: no reliable baseline at all
            base_ok_sources.clear()
        else:
            base_unavailable_paths.add(rename_map.get(entry["path"], entry["path"]))

    classifiable_head: list[Finding] = []
    unclassified: list[Finding] = []
    for finding in head_result.findings:
        if finding.source in base_ok_sources and finding.file_path not in base_unavailable_paths:
            classifiable_head.append(finding)
        else:
            unclassified.append(finding)

    classifiable_base = [f for f in base_result.findings if f.source in base_ok_sources]
    differential = classify(classifiable_head, classifiable_base, diffs)
    all_findings = differential.findings + unclassified

    reasons: list[str] = []
    if head_result.overall_status == "failed":
        status, code = "failed", "analysis_failed"
        reasons.append("head_analysis_failed")
    else:
        status, code = "completed", None
        if not head_result.analysis_complete:
            status, code = "partial", "analysis_incomplete"
            reasons.extend(f"head:{r}" for r in head_result.incomplete_reasons)
        if base_ok_sources != {"ESLINT", "SEMGREP"} or base_result.overall_status != "completed":
            status, code = "partial", "differential_incomplete"
            reasons.append(f"base_analysis_{base_result.overall_status}")
        if base_unavailable_paths:
            status, code = "partial", "differential_incomplete"
            reasons.append("base_content_unavailable")
        snapshot_incomplete = [
            e for e in snapshot.skipped if e["reason"] not in ("not_analyzable_type",)
        ]
        if snapshot_incomplete:
            status, code = "partial", code or "analysis_incomplete"
            reasons.append("snapshot_skipped_files")

    error_message = "; ".join(
        m for m in (head_result.error_summary, base_result.error_summary) if m
    ) or None
    if status == "partial" and not error_message:
        error_message = "incomplete: " + ", ".join(sorted(set(reasons)))

    skipped_by_reason: dict[str, int] = {}
    for entry in snapshot.skipped:
        skipped_by_reason[entry["reason"]] = skipped_by_reason.get(entry["reason"], 0) + 1

    meta: dict[str, Any] = {
        "snapshot": {
            "head_sha": snapshot.head_sha,
            "base_sha": snapshot.base_sha,
            "merge_base_sha": snapshot.merge_base_sha,
            "changed_files_total": snapshot.changed_files_total,
            "files_selected": len(snapshot.files),
            "skipped_by_reason": skipped_by_reason,
        },
        "head": head_result.meta(),
        "base": base_result.meta(),
        "differential": {
            "new": differential.new_count,
            "existing": differential.existing_count,
            "moved": differential.moved_count,
            "fixed": differential.fixed_count,
            "unclassified": len(unclassified),
            "diff_sources": _count_by(diffs.values(), lambda d: d.source),
        },
        "incomplete_reasons": sorted(set(reasons)),
    }
    return AnalysisOutcome(status, all_findings, meta, code, redact_secrets(error_message))


def _count_by(items, key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        out[k] = out.get(k, 0) + 1
    return out


__all__ = ["execute_review_run", "analyze_snapshot", "backoff_seconds", "StaticAnalysisResult"]
