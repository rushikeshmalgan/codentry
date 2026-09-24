"""A small in-process fake of the GitHub REST endpoints the snapshot fetcher
uses, mounted on respx. This is a MOCK: it proves our client logic against
the response shapes we expect, not GitHub's real behavior.
"""

from __future__ import annotations

import base64
from urllib.parse import quote

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

API = "https://api.github.com"

_KEY: str | None = None


def private_key_pem() -> str:
    global _KEY
    if _KEY is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _KEY = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
    return _KEY


def file_body(text: str, sha: str = "blob1", type_: str = "file") -> dict:
    raw = text.encode("utf-8")
    return {
        "type": type_,
        "encoding": "base64",
        "size": len(raw),
        "sha": sha,
        "content": base64.b64encode(raw).decode(),
    }


def entry(path, status="modified", sha="blob1", patch="@@ -1 +1 @@\n-a\n+b\n", previous=None):
    e = {"filename": path, "status": status, "sha": sha, "patch": patch}
    if previous:
        e["previous_filename"] = previous
    if patch is None:
        e.pop("patch")
    return e


class FakeGitHub:
    def __init__(self, repo="octo/widgets", pr=1, head="headsha", base="basesha",
                 merge_base="mbsha", installation=999):
        self.repo, self.pr, self.head, self.base = repo, pr, head, base
        self.merge_base, self.installation = merge_base, installation
        self.listing: list[dict] = []
        self.changed_files: int | None = None  # None => len(listing)
        self.contents: dict[tuple[str, str], object] = {}
        self.head_sequence: list[str] = [head]
        self.page_size = 100
        self.token_status = 201
        self.pull_response: httpx.Response | None = None
        self.pull_exception: Exception | None = None
        self.calls: list[str] = []
        self.content_requests: list[tuple[str, str]] = []

    # --- configuration helpers ---------------------------------------------
    def add_file(self, path: str, ref: str, text: str, sha: str = "blob1") -> None:
        self.contents[(path, ref)] = file_body(text, sha)

    # --- handlers ------------------------------------------------------------
    def _pull(self, request: httpx.Request) -> httpx.Response:
        self.calls.append("pull")
        if self.pull_exception is not None:
            raise self.pull_exception
        if self.pull_response is not None:
            return self.pull_response
        idx = min(self.calls.count("pull") - 1, len(self.head_sequence) - 1)
        total = self.changed_files if self.changed_files is not None else len(self.listing)
        return httpx.Response(
            200,
            json={
                "head": {"sha": self.head_sequence[idx]},
                "base": {"sha": self.base},
                "changed_files": total,
            },
        )

    def _compare(self, request: httpx.Request) -> httpx.Response:
        self.calls.append("compare")
        return httpx.Response(200, json={"merge_base_commit": {"sha": self.merge_base}})

    def _files(self, request: httpx.Request) -> httpx.Response:
        self.calls.append("files")
        page = int(request.url.params.get("page", "1"))
        start = (page - 1) * self.page_size
        chunk = self.listing[start : start + self.page_size]
        headers = {}
        if start + self.page_size < len(self.listing):
            next_url = (
                f"{API}/repos/{self.repo}/pulls/{self.pr}/files"
                f"?per_page={self.page_size}&page={page + 1}"
            )
            headers["Link"] = f'<{next_url}>; rel="next"'
        return httpx.Response(200, json=chunk, headers=headers)

    def _contents(self, request: httpx.Request) -> httpx.Response:
        prefix = f"/repos/{self.repo}/contents/"
        path = request.url.path[len(prefix):]
        from urllib.parse import unquote

        path = unquote(path)
        ref = request.url.params.get("ref", "")
        self.content_requests.append((path, ref))
        found = self.contents.get((path, ref))
        if found is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if isinstance(found, httpx.Response):
            return found
        return httpx.Response(200, json=found)

    # --- mount ----------------------------------------------------------------
    def mount(self, mock: respx.MockRouter) -> None:
        mock.post(f"{API}/app/installations/{self.installation}/access_tokens").mock(
            return_value=httpx.Response(
                self.token_status,
                json={"token": "ghs_faketoken", "expires_at": "2099-01-01T00:00:00Z"},
            )
        )
        mock.get(f"{API}/repos/{self.repo}/pulls/{self.pr}").mock(side_effect=self._pull)
        mock.get(url__startswith=f"{API}/repos/{self.repo}/compare/").mock(side_effect=self._compare)
        mock.get(f"{API}/repos/{self.repo}/pulls/{self.pr}/files").mock(side_effect=self._files)
        mock.get(url__startswith=f"{API}/repos/{self.repo}/contents/").mock(
            side_effect=self._contents
        )


__all__ = ["FakeGitHub", "entry", "file_body", "private_key_pem", "quote"]
