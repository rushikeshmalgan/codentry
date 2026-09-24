"""Fetches changed-file content for a PR via the Phase 2 GitHub App
installation token.

This is the one module in `analysis/` that depends on `app.*` (reusing
app.github_auth's JWT/token minting rather than inventing a second auth
system, per spec) and makes real network calls to GitHub. Nothing else in
`analysis/` imports this module, and the standalone CLI (`analysis.run`)
never does — see tests/test_analysis_cli.py's zero-AI/GitHub/Supabase proof,
which would fail if that ever changed.

Not exercised against live GitHub in this environment (no registered App —
see docs/github-app-setup.md). Tested here against a mocked HTTP transport
(respx), matching the precedent set in services/ai-review/app/github_auth.py.
"""

from __future__ import annotations

import base64
import logging

import httpx

from analysis.workspace import SourceFile
from app.github_auth import GitHubAuthError, get_installation_access_token

logger = logging.getLogger("codentry.ai_review.analysis.changed_files")

GITHUB_API_BASE = "https://api.github.com"
MAX_FILES = 100
REQUEST_TIMEOUT_SECONDS = 15.0


class ChangedFilesError(RuntimeError):
    """Raised on any failure to authenticate or fetch PR file data from GitHub."""


async def fetch_changed_files(
    app_id: str,
    private_key_pem: str,
    github_installation_id: int,
    repo_full_name: str,
    pr_number: int,
) -> list[SourceFile]:
    """Returns SourceFile[] for every added/modified file in the PR.

    Removed files are skipped entirely — there is nothing to statically
    analyze in a deletion. A file whose content can't be fetched or decoded
    as UTF-8 (binary, or a transient GitHub error) is skipped and logged,
    not treated as a fatal error for the whole PR.
    """
    try:
        token, _ = await get_installation_access_token(
            app_id, private_key_pem, github_installation_id
        )
    except GitHubAuthError as exc:
        raise ChangedFilesError(f"could not authenticate to GitHub: {exc}") from exc

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        file_entries = await _list_pr_files(client, headers, repo_full_name, pr_number)

        source_files: list[SourceFile] = []
        for entry in file_entries:
            if entry.get("status") == "removed":
                continue
            path = entry.get("filename")
            if not path:
                continue
            content = await _fetch_file_content(client, headers, path, entry)
            if content is not None:
                source_files.append(SourceFile(path=path, content=content))

    return source_files


async def _list_pr_files(
    client: httpx.AsyncClient, headers: dict[str, str], repo_full_name: str, pr_number: int
) -> list[dict]:
    url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}/files"
    try:
        response = await client.get(url, headers=headers, params={"per_page": 100})
    except httpx.HTTPError as exc:
        raise ChangedFilesError(f"failed to list PR files: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise ChangedFilesError(f"GitHub returned {response.status_code} listing PR files")

    entries = response.json()
    if len(entries) > MAX_FILES:
        logger.warning("changed_files_truncated total=%d max=%d", len(entries), MAX_FILES)
        entries = entries[:MAX_FILES]
    return entries


async def _fetch_file_content(
    client: httpx.AsyncClient, headers: dict[str, str], path: str, entry: dict
) -> str | None:
    # `contents_url` is provided by GitHub's PR-files response already
    # pointing at the PR head commit (it embeds `?ref=<sha>`) — reused
    # directly rather than reconstructed.
    contents_url = entry.get("contents_url")
    if not contents_url:
        return None

    try:
        response = await client.get(contents_url, headers=headers)
    except httpx.HTTPError:
        logger.warning("file_content_fetch_failed path=%s", path)
        return None

    if response.status_code != 200:
        logger.warning("file_content_fetch_status path=%s status=%d", path, response.status_code)
        return None

    body = response.json()
    if body.get("encoding") != "base64" or "content" not in body:
        return None

    try:
        raw_bytes = base64.b64decode(body["content"])
        return raw_bytes.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        logger.info("file_content_binary_skipped path=%s", path)
        return None
