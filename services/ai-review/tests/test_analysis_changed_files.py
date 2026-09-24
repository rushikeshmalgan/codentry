"""Mocked-HTTP tests (respx) for analysis/changed_files.py — no live GitHub
App exists in this environment, so this is the honest ceiling of what can
be verified here. See docs/staging-test-phase2.md for the real procedure."""

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from analysis.changed_files import ChangedFilesError, fetch_changed_files


def _test_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _mock_token_endpoint(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/999/access_tokens").mock(
        return_value=httpx.Response(
            201, json={"token": "ghs_faketoken", "expires_at": "2026-01-01T00:00:00Z"}
        )
    )


@pytest.mark.anyio
async def test_fetch_changed_files_happy_path():
    private_key = _test_private_key()

    with respx.mock:
        _mock_token_endpoint(respx.mock)
        respx.get("https://api.github.com/repos/octo/widgets/pulls/1/files").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "filename": "src/a.js",
                        "status": "modified",
                        "contents_url": "https://api.github.com/repos/octo/widgets/contents/src/a.js?ref=abc123",
                    },
                    {
                        "filename": "src/removed.js",
                        "status": "removed",
                        "contents_url": "https://api.github.com/repos/octo/widgets/contents/src/removed.js?ref=abc123",
                    },
                ],
            )
        )
        respx.get("https://api.github.com/repos/octo/widgets/contents/src/a.js").mock(
            return_value=httpx.Response(
                200,
                json={"encoding": "base64", "content": "Y29uc3QgYSA9IDE7"},  # "const a = 1;"
            )
        )

        files = await fetch_changed_files(
            app_id="12345",
            private_key_pem=private_key,
            github_installation_id=999,
            repo_full_name="octo/widgets",
            pr_number=1,
        )

    assert len(files) == 1
    assert files[0].path == "src/a.js"
    assert files[0].content == "const a = 1;"


@pytest.mark.anyio
async def test_fetch_changed_files_skips_removed_files_without_fetching_content():
    private_key = _test_private_key()

    with respx.mock:
        _mock_token_endpoint(respx.mock)
        respx.get("https://api.github.com/repos/octo/widgets/pulls/1/files").mock(
            return_value=httpx.Response(
                200,
                json=[{"filename": "gone.js", "status": "removed", "contents_url": "should-not-be-called"}],
            )
        )

        files = await fetch_changed_files("12345", private_key, 999, "octo/widgets", 1)

    assert files == []


@pytest.mark.anyio
async def test_fetch_changed_files_skips_binary_content():
    private_key = _test_private_key()

    with respx.mock:
        _mock_token_endpoint(respx.mock)
        respx.get("https://api.github.com/repos/octo/widgets/pulls/1/files").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "filename": "image.png",
                        "status": "added",
                        "contents_url": "https://api.github.com/repos/octo/widgets/contents/image.png",
                    }
                ],
            )
        )
        respx.get("https://api.github.com/repos/octo/widgets/contents/image.png").mock(
            return_value=httpx.Response(200, json={"encoding": "base64", "content": "//79/f4="})
        )

        files = await fetch_changed_files("12345", private_key, 999, "octo/widgets", 1)

    assert files == []


@pytest.mark.anyio
async def test_fetch_changed_files_raises_on_pr_files_list_failure():
    private_key = _test_private_key()

    with respx.mock:
        _mock_token_endpoint(respx.mock)
        respx.get("https://api.github.com/repos/octo/widgets/pulls/1/files").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(ChangedFilesError):
            await fetch_changed_files("12345", private_key, 999, "octo/widgets", 1)


@pytest.mark.anyio
async def test_fetch_changed_files_raises_when_auth_fails():
    private_key = _test_private_key()

    with respx.mock:
        respx.post("https://api.github.com/app/installations/999/access_tokens").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )

        with pytest.raises(ChangedFilesError):
            await fetch_changed_files("12345", private_key, 999, "octo/widgets", 1)


@pytest.mark.anyio
async def test_fetch_changed_files_continues_when_one_file_content_fetch_fails():
    private_key = _test_private_key()

    with respx.mock:
        _mock_token_endpoint(respx.mock)
        respx.get("https://api.github.com/repos/octo/widgets/pulls/1/files").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "filename": "a.js",
                        "status": "modified",
                        "contents_url": "https://api.github.com/repos/octo/widgets/contents/a.js",
                    },
                    {
                        "filename": "b.js",
                        "status": "modified",
                        "contents_url": "https://api.github.com/repos/octo/widgets/contents/b.js",
                    },
                ],
            )
        )
        respx.get("https://api.github.com/repos/octo/widgets/contents/a.js").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://api.github.com/repos/octo/widgets/contents/b.js").mock(
            return_value=httpx.Response(200, json={"encoding": "base64", "content": "Y29uc3QgYiA9IDI7"})
        )

        files = await fetch_changed_files("12345", private_key, 999, "octo/widgets", 1)

    assert len(files) == 1
    assert files[0].path == "b.js"
