"""Fetches a pinned, complete snapshot of a pull request via the GitHub App
installation token.

What "pinned and complete" means here (each point has a test in
tests/test_analysis_changed_files.py):

- Every content read is `?ref=<sha>` against an immutable commit: the
  event's head SHA for the new code, the merge base for the old code, the
  event's base SHA for trusted configuration. Nothing reads "whatever the
  branch points at now".
- The PR head is re-read from the API before and after fetching; if it is no
  longer the SHA this run was created for, the run is stale
  (HeadMovedError) and must be superseded, not reported.
- The changed-file list is paginated via the `Link` header (not silently cut
  at the first 100) and its length is checked against the API's own
  `changed_files` count. A mismatch, or more analyzable files than the hard
  limit, is an error (`too_many_files` / `file_list_incomplete`) — never a
  partial result presented as complete.
- Symlinks, submodules, oversized and non-UTF-8 files are skipped with a
  recorded reason, and a blob-SHA mismatch (the file changed between listing
  and fetch) is recorded rather than trusted.
- Errors are classified as retryable (5xx, network, rate limit) or permanent
  (404, auth), so the job runner can back off or fail correctly.

This is the one module in `analysis/` that depends on `app.*` (reusing
app.github_auth's JWT/token minting rather than inventing a second auth
system) and makes network calls. Nothing else in `analysis/` imports it, and
the standalone CLI never does — tests/test_analysis_cli.py proves that.

Not exercised against live GitHub in this environment (no registered App —
docs/first-deployment-runbook.md). Tested against a mocked HTTP transport
(respx). That is mocked verification, not real GitHub verification.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from analysis.limits import MAX_FILE_BYTES, MAX_FILES
from analysis.trusted_config import TRUSTED_CONFIG_FILENAME
from analysis.workspace import (
    SKIP_BASE_UNAVAILABLE,
    SKIP_BINARY,
    SKIP_BLOB_MISMATCH,
    SKIP_FETCH_FAILED,
    SKIP_NOT_ANALYZABLE,
    SKIP_SYMLINK,
    SKIP_TOO_LARGE,
    SKIP_UNSAFE_PATH,
    SourceFile,
    is_analyzable,
    is_control_file,
    is_vendored,
    unsafe_path_reason,
)
from app.github_auth import GitHubAuthError, get_installation_access_token

logger = logging.getLogger("codentry.ai_review.analysis.changed_files")

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 15.0
FILES_PER_PAGE = 100
MAX_LIST_PAGES = 30  # GitHub caps the files endpoint at 3000 files (30 x 100)
FETCH_CONCURRENCY = 8
SNAPSHOT_DEADLINE_SECONDS = 180.0


class SnapshotError(RuntimeError):
    """Any failure to build the snapshot. `retryable` says whether the job
    runner should back off and try again; `retry_after` is a hint in seconds."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after


class HeadMovedError(SnapshotError):
    """The PR head is no longer the SHA this run was created for."""

    def __init__(self, expected: str, actual: str | None) -> None:
        super().__init__(
            "head_moved", f"expected {expected[:12]}, PR head is now {(actual or '?')[:12]}"
        )
        self.expected = expected
        self.actual = actual


# Kept for callers/tests written against the Phase 3 name.
ChangedFilesError = SnapshotError


@dataclass
class ChangedFile:
    path: str  # path at the head (the identity path)
    status: str  # added | modified | removed | renamed | copied | changed
    previous_path: str | None = None
    patch: str | None = None
    head: SourceFile | None = None
    base: SourceFile | None = None
    # True when the file existed before the PR but its old content could not
    # be read. Its findings cannot be classified new-vs-existing and must not
    # be treated as new (that would blame the PR for pre-existing code).
    base_unavailable: bool = False


@dataclass
class PullRequestSnapshot:
    repo_full_name: str
    pr_number: int
    head_sha: str
    base_sha: str
    merge_base_sha: str
    files: list[ChangedFile] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    changed_files_total: int = 0
    trusted_config_text: str | None = None

    @property
    def head_files(self) -> list[SourceFile]:
        return [f.head for f in self.files if f.head is not None]

    @property
    def base_files(self) -> list[SourceFile]:
        return [f.base for f in self.files if f.base is not None]

    @property
    def rename_map(self) -> dict[str, str]:
        """base path -> head path, for renamed files."""
        return {f.previous_path: f.path for f in self.files if f.previous_path}


def _raise_for_status(response: httpx.Response, what: str) -> None:
    code = response.status_code
    if code == 200:
        return
    retry_after: float | None = None
    header = response.headers.get("retry-after")
    if header and header.isdigit():
        retry_after = float(header)

    if code == 404:
        raise SnapshotError("not_found", f"{what} returned 404")
    if code in (429,) or (
        code == 403
        and (response.headers.get("x-ratelimit-remaining") == "0" or retry_after is not None)
    ):
        raise SnapshotError(
            "rate_limited", f"{what} rate limited ({code})", retryable=True, retry_after=retry_after
        )
    if code in (401, 403):
        raise SnapshotError("auth", f"{what} returned {code}")
    if code >= 500:
        raise SnapshotError("server", f"{what} returned {code}", retryable=True)
    raise SnapshotError("unexpected_status", f"{what} returned {code}")


async def _get(
    client: httpx.AsyncClient, url: str, what: str, params: dict | None = None
) -> httpx.Response:
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise SnapshotError("network", f"{what}: {type(exc).__name__}", retryable=True) from exc
    return response


async def _get_ok(
    client: httpx.AsyncClient, url: str, what: str, params: dict | None = None
) -> httpx.Response:
    response = await _get(client, url, what, params)
    _raise_for_status(response, what)
    return response


async def _fetch_pull(client: httpx.AsyncClient, repo: str, number: int) -> dict:
    response = await _get_ok(
        client, f"{GITHUB_API_BASE}/repos/{repo}/pulls/{number}", "get pull request"
    )
    return response.json()


async def _assert_head_unchanged(
    client: httpx.AsyncClient, repo: str, number: int, expected_head_sha: str
) -> dict:
    pull = await _fetch_pull(client, repo, number)
    actual = ((pull.get("head") or {}).get("sha")) or None
    if actual != expected_head_sha:
        raise HeadMovedError(expected_head_sha, actual)
    return pull


async def _merge_base(client: httpx.AsyncClient, repo: str, base_sha: str, head_sha: str) -> str:
    response = await _get_ok(
        client,
        f"{GITHUB_API_BASE}/repos/{repo}/compare/{base_sha}...{head_sha}",
        "compare base and head",
        params={"per_page": 1},
    )
    sha = ((response.json().get("merge_base_commit") or {}).get("sha")) or None
    if not sha:
        raise SnapshotError("incomplete", "compare response had no merge_base_commit")
    return sha


async def _list_pull_files(
    client: httpx.AsyncClient, repo: str, number: int, expected_total: int | None
) -> list[dict]:
    """Every file entry, following `Link: rel=next`, verified against the API's count."""
    url: str | None = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{number}/files"
    params: dict | None = {"per_page": FILES_PER_PAGE}
    entries: list[dict] = []
    pages = 0

    while url:
        pages += 1
        if pages > MAX_LIST_PAGES:
            raise SnapshotError(
                "too_many_files", f"more than {MAX_LIST_PAGES * FILES_PER_PAGE} changed files"
            )
        response = await _get_ok(client, url, "list pull request files", params=params)
        entries.extend(response.json())
        url = (response.links.get("next") or {}).get("url")
        params = None  # the `next` URL already carries its own query string

    if expected_total is not None and len(entries) != expected_total:
        raise SnapshotError(
            "file_list_incomplete",
            f"listed {len(entries)} files but the pull request reports {expected_total}",
            retryable=True,
        )
    return entries


@dataclass
class _Fetched:
    source: SourceFile | None = None
    skip_reason: str | None = None


async def _fetch_content(
    client: httpx.AsyncClient,
    repo: str,
    path: str,
    ref: str,
    expected_blob_sha: str | None = None,
) -> _Fetched:
    url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{quote(path, safe='/')}"
    response = await _get(client, url, f"fetch {path}", params={"ref": ref})

    if response.status_code == 404:
        return _Fetched(skip_reason=SKIP_FETCH_FAILED)
    try:
        _raise_for_status(response, f"fetch {path}")
    except SnapshotError as exc:
        if exc.retryable:
            raise
        return _Fetched(skip_reason=SKIP_FETCH_FAILED)

    body = response.json()
    if not isinstance(body, dict):  # a directory listing
        return _Fetched(skip_reason=SKIP_SYMLINK)
    if body.get("type") != "file":  # symlink, submodule, ...
        return _Fetched(skip_reason=SKIP_SYMLINK)
    if expected_blob_sha and body.get("sha") != expected_blob_sha:
        return _Fetched(skip_reason=SKIP_BLOB_MISMATCH)
    if (body.get("size") or 0) > MAX_FILE_BYTES:
        return _Fetched(skip_reason=SKIP_TOO_LARGE)
    if body.get("encoding") != "base64" or "content" not in body:
        return _Fetched(skip_reason=SKIP_FETCH_FAILED)

    try:
        text = base64.b64decode(body["content"]).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return _Fetched(skip_reason=SKIP_BINARY)
    return _Fetched(source=SourceFile(path=path, content=text))


async def _fetch_trusted_config(client: httpx.AsyncClient, repo: str, base_sha: str) -> str | None:
    """`.eslintrc.json` at the trusted BASE commit, or None if the repo has none."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{TRUSTED_CONFIG_FILENAME}"
    response = await _get(client, url, "fetch trusted config", params={"ref": base_sha})
    if response.status_code == 404:
        return None
    _raise_for_status(response, "fetch trusted config")
    body = response.json()
    if not isinstance(body, dict) or body.get("type") != "file" or body.get("encoding") != "base64":
        return None
    try:
        return base64.b64decode(body["content"]).decode("utf-8")
    except (UnicodeDecodeError, ValueError, KeyError):
        return None


def _candidates(entries: list[dict]) -> tuple[list[dict], list[dict[str, str]]]:
    """Splits listed entries into files to fetch and recorded skips."""
    wanted: list[dict] = []
    skipped: list[dict[str, str]] = []
    for entry in entries:
        path = entry.get("filename")
        if not isinstance(path, str) or unsafe_path_reason(path) is not None:
            skipped.append({"path": str(path)[:200], "reason": SKIP_UNSAFE_PATH})
            continue
        previous = entry.get("previous_filename")
        if isinstance(previous, str) and unsafe_path_reason(previous) is not None:
            skipped.append({"path": path, "reason": SKIP_UNSAFE_PATH})
            continue
        if is_control_file(path) or is_vendored(path) or not is_analyzable(path):
            # Benign: nothing to statically analyze (recorded for transparency).
            skipped.append({"path": path, "reason": SKIP_NOT_ANALYZABLE})
            continue
        wanted.append(entry)
    return wanted, skipped


async def fetch_pull_request_snapshot(
    app_id: str,
    private_key_pem: str,
    github_installation_id: int,
    repo_full_name: str,
    pr_number: int,
    *,
    expected_head_sha: str,
    base_sha: str | None = None,
) -> PullRequestSnapshot:
    """Builds a pinned, complete snapshot or raises SnapshotError/HeadMovedError."""
    try:
        async with asyncio.timeout(SNAPSHOT_DEADLINE_SECONDS):
            return await _build_snapshot(
                app_id,
                private_key_pem,
                github_installation_id,
                repo_full_name,
                pr_number,
                expected_head_sha,
                base_sha,
            )
    except TimeoutError as exc:
        raise SnapshotError(
            "timeout", f"snapshot exceeded {SNAPSHOT_DEADLINE_SECONDS:g}s", retryable=True
        ) from exc


async def _build_snapshot(
    app_id: str,
    private_key_pem: str,
    github_installation_id: int,
    repo: str,
    pr_number: int,
    expected_head_sha: str,
    base_sha: str | None,
) -> PullRequestSnapshot:
    try:
        token, _ = await get_installation_access_token(
            app_id, private_key_pem, github_installation_id
        )
    except GitHubAuthError as exc:
        status = getattr(exc, "status_code", None)
        transient = status is None or status >= 500 or status == 429
        raise SnapshotError(
            "auth", f"could not authenticate to GitHub: {exc}", retryable=transient
        ) from exc

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
        pull = await _assert_head_unchanged(client, repo, pr_number, expected_head_sha)
        pinned_base = base_sha or ((pull.get("base") or {}).get("sha"))
        if not pinned_base:
            raise SnapshotError("incomplete", "pull request has no base sha")
        merge_base = await _merge_base(client, repo, pinned_base, expected_head_sha)

        total = pull.get("changed_files")
        if isinstance(total, int) and total > MAX_LIST_PAGES * FILES_PER_PAGE:
            raise SnapshotError(
                "too_many_files",
                f"{total} changed files exceeds the "
                f"{MAX_LIST_PAGES * FILES_PER_PAGE} GitHub can list",
            )
        entries = await _list_pull_files(
            client, repo, pr_number, total if isinstance(total, int) else None
        )
        wanted, skipped = _candidates(entries)
        if len(wanted) > MAX_FILES:
            raise SnapshotError(
                "too_many_files", f"{len(wanted)} analyzable changed files > limit {MAX_FILES}"
            )

        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def build(entry: dict) -> ChangedFile:
            path = entry["filename"]
            status = entry.get("status", "modified")
            previous = entry.get("previous_filename") if status in ("renamed", "copied") else None
            changed = ChangedFile(
                path=path,
                status=status,
                previous_path=previous if status == "renamed" else None,
                patch=entry.get("patch"),
            )
            async with semaphore:
                if status != "removed":
                    got = await _fetch_content(
                        client, repo, path, expected_head_sha, entry.get("sha")
                    )
                    changed.head = got.source
                    if got.skip_reason:
                        skipped.append({"path": path, "reason": got.skip_reason})
                if status != "added":
                    base_path = previous or path
                    got = await _fetch_content(client, repo, base_path, merge_base)
                    changed.base = got.source
                    if got.source is None:
                        changed.base_unavailable = True
                        skipped.append({"path": base_path, "reason": SKIP_BASE_UNAVAILABLE})
            return changed

        files = list(await asyncio.gather(*(build(e) for e in wanted)))
        config_text = await _fetch_trusted_config(client, repo, pinned_base)

        # The head must not have moved while we were reading it.
        await _assert_head_unchanged(client, repo, pr_number, expected_head_sha)

    return PullRequestSnapshot(
        repo_full_name=repo,
        pr_number=pr_number,
        head_sha=expected_head_sha,
        base_sha=pinned_base,
        merge_base_sha=merge_base,
        files=files,
        skipped=skipped,
        changed_files_total=len(entries),
        trusted_config_text=config_text,
    )
