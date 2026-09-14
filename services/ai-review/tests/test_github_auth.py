"""GitHub App auth: JWT construction is verified against a locally generated
throwaway RSA keypair (no real GitHub App needed for this). Installation
token minting is verified against a mocked HTTP call via respx — this
proves the request is built correctly (URL, headers, error handling), not
that a real GitHub App can authenticate (that requires a live App; see
docs/github-app-setup.md, marked USER ACTION REQUIRED).
"""

import httpx
import jwt as pyjwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.github_auth import (
    GitHubAuthError,
    build_app_jwt,
    get_installation_access_token,
    normalize_private_key,
)


def _generate_test_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def test_normalize_private_key_unescapes_literal_newlines():
    assert normalize_private_key("line1\\nline2") == "line1\nline2"
    assert normalize_private_key("already\nreal\nnewlines") == "already\nreal\nnewlines"


def test_build_app_jwt_has_expected_claims_and_verifies():
    private_pem, public_pem = _generate_test_keypair()

    token = build_app_jwt("12345", private_pem)
    decoded = pyjwt.decode(
        token, public_pem, algorithms=["RS256"], options={"require": ["iat", "exp", "iss"]}
    )

    assert decoded["iss"] == "12345"
    assert decoded["exp"] > decoded["iat"]
    # GitHub caps App JWT lifetime at 10 minutes; confirm we stay comfortably under.
    assert decoded["exp"] - decoded["iat"] <= 10 * 60 + 60


def test_build_app_jwt_handles_escaped_newline_private_key():
    private_pem, public_pem = _generate_test_keypair()
    escaped = private_pem.replace("\n", "\\n")

    token = build_app_jwt("999", escaped)
    decoded = pyjwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "999"


@pytest.mark.anyio
async def test_get_installation_access_token_success():
    private_pem, _ = _generate_test_keypair()

    with respx.mock:
        route = respx.post("https://api.github.com/app/installations/999/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_faketoken", "expires_at": "2026-01-01T00:00:00Z"}
            )
        )
        token, expires_at = await get_installation_access_token("12345", private_pem, 999)

    assert token == "ghs_faketoken"
    assert expires_at == "2026-01-01T00:00:00Z"
    sent_request = route.calls[0].request
    assert sent_request.headers["Authorization"].startswith("Bearer ")
    assert sent_request.headers["Accept"] == "application/vnd.github+json"


@pytest.mark.anyio
async def test_get_installation_access_token_failure_raises_without_leaking_secrets():
    private_pem, _ = _generate_test_keypair()

    with respx.mock:
        respx.post("https://api.github.com/app/installations/999/access_tokens").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(GitHubAuthError) as exc_info:
            await get_installation_access_token("12345", private_pem, 999)

    assert private_pem not in str(exc_info.value)
