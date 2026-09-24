"""Shared builders for job-lifecycle tests (store, worker, runner)."""

from __future__ import annotations

from datetime import datetime, timezone

from analysis.changed_files import ChangedFile, PullRequestSnapshot
from analysis.workspace import SourceFile
from app.config import Settings
from app.events import handle_pull_request_event
from tests.github_payloads import pull_request_payload


def now() -> datetime:
    """The real clock. Store methods stamp jobs with it, so tests that claim
    jobs must use it too (a frozen clock would put enqueue times in the future)."""
    return datetime.now(timezone.utc)


def configured_settings(**overrides) -> Settings:
    values = dict(
        github_app_id="12345",
        github_private_key="not-a-real-key",
        worker_enabled=False,
        job_lease_seconds=600,
    )
    values.update(overrides)
    return Settings(**values)


def enqueue(store, *, head_sha="head-aaa", base_sha="base-aaa", pr_number=1, repo_id=222,
            action="opened", updated_at=None, delivery_id="d-1"):
    """Runs the real event handler and returns (run_row, result_dict)."""
    payload = pull_request_payload(
        action=action, head_sha=head_sha, base_sha=base_sha, pr_number=pr_number, repo_id=repo_id
    )
    if updated_at:
        payload["pull_request"]["updated_at"] = updated_at
    result = handle_pull_request_event(store, payload, delivery_id=delivery_id)
    run = store.get_review_run(result["review_run_id"]) if result["review_run_id"] else None
    return run, result


def claim(store, at=None, lease=600):
    return store.claim_next_review_run(lease, now=at or now())


def snapshot(files: list[ChangedFile], *, head="head-aaa", base="base-aaa",
             merge_base="merge-aaa", skipped=None, config_text=None) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        repo_full_name="octo-team/widgets",
        pr_number=1,
        head_sha=head,
        base_sha=base,
        merge_base_sha=merge_base,
        files=files,
        skipped=skipped or [],
        changed_files_total=len(files),
        trusted_config_text=config_text,
    )


def changed(path, *, head=None, base=None, status=None, patch=None, previous=None,
            base_unavailable=False) -> ChangedFile:
    status = status or ("added" if base is None else "removed" if head is None else "modified")
    return ChangedFile(
        path=path,
        status=status,
        previous_path=previous,
        patch=patch,
        head=SourceFile(path, head) if head is not None else None,
        base=SourceFile(previous or path, base) if base is not None else None,
        base_unavailable=base_unavailable,
    )


def fake_fetcher(result=None, error=None):
    """A drop-in for fetch_pull_request_snapshot that records its calls."""
    calls = []

    async def fetcher(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return result

    fetcher.calls = calls
    return fetcher
