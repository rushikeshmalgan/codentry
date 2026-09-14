"""Business-logic tests, no HTTP — directly against InMemoryReviewStore."""

import pytest

from app.events import (
    EventPayloadError,
    handle_installation_event,
    handle_installation_repositories_event,
    handle_pull_request_event,
)
from tests.github_payloads import (
    installation_payload,
    installation_repositories_payload,
    pull_request_payload,
)


def test_pull_request_opened_creates_pending_review_run(store):
    result = handle_pull_request_event(store, pull_request_payload(action="opened"))

    assert result["review_run_id"] is not None
    run = store.get_review_run(result["review_run_id"])
    assert run["status"] == "pending"
    assert run["trigger_event"] == "opened"


def test_pull_request_synchronize_and_reopened_also_create_runs(store):
    for action in ("synchronize", "reopened"):
        result = handle_pull_request_event(
            store, pull_request_payload(action=action, repo_id=300, pr_number=1)
        )
        assert result["review_run_id"] is not None


def test_pull_request_unsupported_action_creates_no_review_run(store):
    result = handle_pull_request_event(store, pull_request_payload(action="labeled"))

    assert result["review_run_id"] is None
    assert result["reason"] == "unsupported_action"


def test_pull_request_on_inactive_repository_creates_no_review_run(store):
    handle_pull_request_event(store, pull_request_payload(action="opened", repo_id=999, pr_number=1))
    store.set_repository_active(999, is_active=False)

    result = handle_pull_request_event(
        store, pull_request_payload(action="synchronize", repo_id=999, pr_number=1)
    )

    assert result["review_run_id"] is None
    assert result["reason"] == "repository_inactive"
    # PR bookkeeping still happens even when the repo is inactive.
    repo = store.get_repository_by_github_id(999)
    assert repo is not None


def test_pull_request_missing_required_fields_raises(store):
    with pytest.raises(EventPayloadError):
        handle_pull_request_event(store, {"action": "opened"})


def test_pull_request_creates_installation_and_repository_defensively(store):
    """Covers the case where the `installation` event was never received."""
    result = handle_pull_request_event(
        store, pull_request_payload(installation_id=42, repo_id=43, repo_full_name="acme/x")
    )

    assert result["review_run_id"] is not None
    repo = store.get_repository_by_github_id(43)
    assert repo["full_name"] == "acme/x"
    assert repo["is_active"] is True


def test_installation_created_upserts_repositories(store):
    handle_installation_event(
        store,
        installation_payload(
            action="created",
            installation_id=1,
            login="octo-team",
            repos=[{"id": 10, "full_name": "octo-team/one"}],
        ),
    )

    repo = store.get_repository_by_github_id(10)
    assert repo is not None
    assert repo["is_active"] is True


def test_installation_deleted_deactivates_all_its_repositories(store):
    handle_installation_event(
        store,
        installation_payload(
            action="created",
            installation_id=2,
            repos=[
                {"id": 20, "full_name": "octo-team/two"},
                {"id": 21, "full_name": "octo-team/three"},
            ],
        ),
    )

    handle_installation_event(store, installation_payload(action="deleted", installation_id=2))

    assert store.get_repository_by_github_id(20)["is_active"] is False
    assert store.get_repository_by_github_id(21)["is_active"] is False


def test_installation_deleted_keeps_installation_row_traceable(store):
    handle_installation_event(
        store, installation_payload(action="created", installation_id=3, login="octo-team")
    )
    handle_installation_event(store, installation_payload(action="deleted", installation_id=3))

    summaries = store.list_installations_summary()
    assert any(s["github_installation_id"] == 3 for s in summaries)


def test_installation_missing_id_raises(store):
    with pytest.raises(EventPayloadError):
        handle_installation_event(store, {"action": "created", "installation": {}})


def test_installation_repositories_added_then_removed(store):
    handle_installation_repositories_event(
        store,
        installation_repositories_payload(
            action="added", added=[{"id": 30, "full_name": "octo-team/four"}]
        ),
    )
    assert store.get_repository_by_github_id(30)["is_active"] is True

    handle_installation_repositories_event(
        store, installation_repositories_payload(action="removed", removed=[{"id": 30}])
    )
    assert store.get_repository_by_github_id(30)["is_active"] is False


def test_upsert_repository_never_reactivates_a_deactivated_repo(store):
    handle_pull_request_event(store, pull_request_payload(repo_id=5, action="opened"))
    store.set_repository_active(5, is_active=False)

    # A second pull_request event for the same repo must NOT silently flip
    # is_active back to true just because it upserts full_name/default_branch.
    handle_pull_request_event(store, pull_request_payload(repo_id=5, action="synchronize", pr_number=1))

    assert store.get_repository_by_github_id(5)["is_active"] is False


def test_pull_request_upsert_updates_existing_pr_not_duplicate(store):
    handle_pull_request_event(
        store, pull_request_payload(repo_id=7, pr_number=1, action="opened", title="v1")
    )
    handle_pull_request_event(
        store, pull_request_payload(repo_id=7, pr_number=1, action="synchronize", title="v2")
    )

    repo = store.get_repository_by_github_id(7)
    pr_rows = [
        pr for pr in store._pull_requests.values() if pr["repository_id"] == repo["id"]  # noqa: SLF001
    ]
    assert len(pr_rows) == 1
    assert pr_rows[0]["title"] == "v2"
