"""Business logic for the three supported GitHub event types.

Deliberately separate from app/routes_internal.py so it can be unit tested
directly against InMemoryReviewStore without going through HTTP at all.
GitHub's payloads are treated as untrusted, partially-shaped input: every
field access is defensive (`.get()` with fallbacks), and a payload missing
something a handler truly cannot proceed without raises EventPayloadError,
which the route layer turns into a 400 rather than a 500.
"""

from __future__ import annotations

from typing import Any

from app.store import ReviewStore

ALLOWED_PULL_REQUEST_ACTIONS = {"opened", "synchronize", "reopened"}


class EventPayloadError(ValueError):
    """Raised when a payload is missing a field its handler cannot proceed without."""


def handle_installation_event(store: ReviewStore, payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    installation = payload.get("installation") or {}
    github_installation_id = installation.get("id")
    if github_installation_id is None:
        raise EventPayloadError("installation.id missing from installation event")

    account = installation.get("account") or {}
    inst_row = store.upsert_installation(
        github_installation_id, account.get("login"), account.get("type")
    )

    if action == "deleted":
        deactivated = store.deactivate_repositories_for_installation(github_installation_id)
        return {"action": action, "deactivated_repositories": deactivated}

    # "created", "new_permissions_accepted", "suspend", "unsuspend", etc.
    # Only "created" carries a repositories[] list worth bookkeeping here;
    # other actions are still safely acknowledged (installation row is kept
    # up to date above) but don't touch repositories.
    repositories = payload.get("repositories") or []
    upserted = 0
    for repo in repositories:
        github_repo_id = repo.get("id")
        full_name = repo.get("full_name")
        if github_repo_id is None or full_name is None:
            continue
        # installation.created's repositories[] entries never include
        # default_branch — only the pull_request event's repository object
        # does. Left null here and backfilled later.
        store.upsert_repository(inst_row["id"], github_repo_id, full_name, default_branch=None)
        upserted += 1

    return {"action": action, "repositories_upserted": upserted}


def handle_installation_repositories_event(
    store: ReviewStore, payload: dict[str, Any]
) -> dict[str, Any]:
    action = payload.get("action")  # "added" | "removed"
    installation = payload.get("installation") or {}
    github_installation_id = installation.get("id")
    if github_installation_id is None:
        raise EventPayloadError("installation.id missing from installation_repositories event")

    account = installation.get("account") or {}
    inst_row = store.upsert_installation(
        github_installation_id, account.get("login"), account.get("type")
    )

    added = payload.get("repositories_added") or []
    for repo in added:
        github_repo_id = repo.get("id")
        full_name = repo.get("full_name")
        if github_repo_id is None or full_name is None:
            continue
        store.upsert_repository(inst_row["id"], github_repo_id, full_name, default_branch=None)

    removed_count = 0
    for repo in payload.get("repositories_removed") or []:
        github_repo_id = repo.get("id")
        if github_repo_id is None:
            continue
        if store.set_repository_active(github_repo_id, is_active=False) is not None:
            removed_count += 1

    return {"action": action, "added": len(added), "removed": removed_count}


def handle_pull_request_event(
    store: ReviewStore, payload: dict[str, Any], delivery_id: str | None = None
) -> dict[str, Any]:
    """Bookkeeping plus, for a reviewable event, an IDEMPOTENT job enqueue.

    Every step is an upsert or an idempotent enqueue keyed on
    (pull_request, head_sha), so re-running this for a redelivered or
    reclaimed event cannot create a second review of the same commit.
    """
    action = payload.get("action")
    repository = payload.get("repository") or {}
    pr = payload.get("pull_request") or {}
    installation = payload.get("installation") or {}

    github_repo_id = repository.get("id")
    github_installation_id = installation.get("id")
    pr_number = payload.get("number")

    if github_repo_id is None or github_installation_id is None or pr_number is None:
        raise EventPayloadError(
            "pull_request payload missing repository.id, installation.id, or number"
        )

    # Defensive bookkeeping: creates installation/repository rows if the
    # `installation` event was somehow never received. account_login/
    # account_type and default_branch get backfilled from whatever richer
    # data is available here without clobbering anything already known
    # (see ReviewStore.upsert_* docstrings).
    inst_row = store.upsert_installation(github_installation_id, None, None)
    repo_row = store.upsert_repository(
        inst_row["id"],
        github_repo_id,
        repository.get("full_name") or f"unknown/{github_repo_id}",
        repository.get("default_branch"),
    )

    author = pr.get("user") or {}
    head = pr.get("head") or {}
    base = pr.get("base") or {}

    pr_row = store.upsert_pull_request(
        repository_id=repo_row["id"],
        github_pr_number=pr_number,
        title=pr.get("title"),
        author_login=author.get("login"),
        head_sha=head.get("sha"),
        base_sha=base.get("sha"),
        state=pr.get("state"),
        github_updated_at=pr.get("updated_at"),
    )

    common = {
        "action": action,
        "pull_request_id": pr_row["id"],
        "github_installation_id": github_installation_id,
        "repo_full_name": repo_row["full_name"],
        "github_pr_number": pr_number,
    }

    # An event older than what is already stored must not rewind the PR's head
    # (webhooks can arrive out of order). The worker additionally verifies the
    # head against GitHub itself before analyzing.
    if pr_row.get("stale_event"):
        return {**common, "review_run_id": None, "reason": "stale_event"}

    if action not in ALLOWED_PULL_REQUEST_ACTIONS:
        return {**common, "review_run_id": None, "reason": "unsupported_action"}

    if not repo_row["is_active"]:
        return {**common, "review_run_id": None, "reason": "repository_inactive"}

    head_sha = head.get("sha")
    if not head_sha:
        raise EventPayloadError("pull_request.head.sha missing from pull_request event")

    review_run, created = store.enqueue_review_run(
        pull_request_id=pr_row["id"],
        trigger_event=action,
        head_sha=head_sha,
        base_sha=base.get("sha"),
        delivery_id=delivery_id,
    )
    return {
        **common,
        "review_run_id": review_run["id"],
        "reason": None if created else "already_enqueued",
    }
