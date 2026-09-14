"""Minimal, realistic GitHub webhook payload builders for tests.

Only the fields our handlers actually read are populated — these are not
full GitHub payload fixtures, deliberately, to keep tests readable and to
force handlers to be defensive about fields that aren't here.
"""

from __future__ import annotations

from typing import Any


def pull_request_payload(
    *,
    action: str = "opened",
    installation_id: int = 111,
    repo_id: int = 222,
    repo_full_name: str = "octo-team/widgets",
    pr_number: int = 1,
    title: str = "Fix off-by-one in checkout",
    author_login: str = "junior-dev",
    head_sha: str = "abc123",
    base_sha: str = "def456",
    state: str = "open",
) -> dict[str, Any]:
    return {
        "action": action,
        "number": pr_number,
        "pull_request": {
            "title": title,
            "user": {"login": author_login},
            "head": {"sha": head_sha},
            "base": {"sha": base_sha},
            "state": state,
        },
        "repository": {
            "id": repo_id,
            "full_name": repo_full_name,
            "default_branch": "main",
        },
        "installation": {"id": installation_id},
    }


def installation_payload(
    *,
    action: str = "created",
    installation_id: int = 111,
    login: str = "octo-team",
    account_type: str = "Organization",
    repos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"login": login, "type": account_type},
        },
        "repositories": repos or [],
    }


def installation_repositories_payload(
    *,
    action: str = "added",
    installation_id: int = 111,
    login: str = "octo-team",
    account_type: str = "Organization",
    added: list[dict[str, Any]] | None = None,
    removed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"login": login, "type": account_type},
        },
        "repositories_added": added or [],
        "repositories_removed": removed or [],
    }
