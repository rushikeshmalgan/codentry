"""GitHub App authentication: private key -> App JWT -> installation token.

    GitHub App private key
            |
        App JWT (RS256, <=10 min lifetime)
            |
    installation access token (~1 hour lifetime, minted per-installation)
            |
        GitHub REST API

Not invoked by the Phase 2 pipeline yet — the placeholder background task
never calls the GitHub API (there is nothing for it to fetch or post yet;
that starts in Phase 3, fetching changed files, and Phase 5, posting
comments). This module exists now, fully implemented and unit-tested in
isolation, so those later phases have working auth to build on rather than
inventing it under pressure.

Never logs: the private key, the JWT, the installation token, or any
Authorization header.
"""

from __future__ import annotations

import time

import httpx
import jwt

GITHUB_API_BASE = "https://api.github.com"
JWT_LIFETIME_SECONDS = 9 * 60  # GitHub allows up to 10 minutes; stay under with margin.
JWT_CLOCK_SKEW_SECONDS = 60  # GitHub recommends backdating iat to tolerate clock drift.


class GitHubAuthError(RuntimeError):
    """Raised on any failure to obtain a JWT or installation token.

    The message intentionally never includes the private key, JWT, or any
    token — only the HTTP status / a short reason. `status_code` (None for
    network-level failures) lets callers tell a transient outage (retry)
    from a revoked/misconfigured App (don't).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_private_key(raw_key: str) -> str:
    """Undo the literal-\\n escaping most platform env var UIs force on a PEM.

    If the key already contains real newlines (e.g. loaded from a local
    .env file that supports multiline values), this is a no-op.
    """
    return raw_key.replace("\\n", "\n")


def build_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {
        "iat": now - JWT_CLOCK_SKEW_SECONDS,
        "exp": now + JWT_LIFETIME_SECONDS,
        "iss": app_id,
    }
    key = normalize_private_key(private_key_pem)
    return jwt.encode(payload, key, algorithm="RS256")


async def get_installation_access_token(
    app_id: str,
    private_key_pem: str,
    installation_id: int,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Returns (token, expires_at_iso). Raises GitHubAuthError on failure.

    A fresh client is created (and closed) per call unless one is passed in,
    so callers that already manage a client's lifecycle can reuse it.
    """
    app_jwt = build_app_jwt(app_id, private_key_pem)
    url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(url, headers=headers)
    except httpx.HTTPError as exc:
        raise GitHubAuthError(f"request to GitHub failed: {type(exc).__name__}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code != 201:
        # Deliberately do not include response body/headers in the error —
        # GitHub error responses for this endpoint don't echo secrets back,
        # but there's no upside to logging the full body either.
        raise GitHubAuthError(
            f"GitHub returned {response.status_code} minting installation token",
            status_code=response.status_code,
        )

    body = response.json()
    return body["token"], body["expires_at"]
