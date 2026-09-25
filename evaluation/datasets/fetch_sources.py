"""One-time acquisition of the third-party source files listed in manifest.json.

    python -m evaluation.datasets.fetch_sources            # fetch what is missing, verify the rest
    python -m evaluation.datasets.fetch_sources --refresh  # re-download everything

This is the ONLY place in the harness that touches the network, and it is not
used by tests or by generation: it downloads each file at its pinned commit from
raw.githubusercontent.com (no GitHub API, no credentials), stores it under
``sources/<repo-id>/<path>`` and the repository's license text under
``licenses/<repo-id>.LICENSE``, and records SHA-256 and byte counts back into the
manifest. Afterwards the vendored bytes are what count: generation refuses to run
if any of them no longer matches the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

DATASETS = Path(__file__).resolve().parent
MANIFEST = DATASETS / "manifest.json"
RAW = "https://raw.githubusercontent.com/{owner_repo}/{commit}/{path}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _owner_repo(url: str) -> str:
    return url.removeprefix("https://github.com/").removesuffix("/")


def download(owner_repo: str, commit: str, path: str, attempts: int = 4) -> bytes:
    url = RAW.format(owner_repo=owner_repo, commit=commit, path=path)
    request = urllib.request.Request(url, headers={"User-Agent": "codentry-eval-fetch"})
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except OSError as exc:  # network errors, timeouts, HTTP errors
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def _ensure(path: Path, fetch, expected: str | None, refresh: bool) -> bytes:
    if path.exists() and not refresh:
        data = path.read_bytes()
        if expected is not None and _sha256(data) != expected:
            raise RuntimeError(f"{path} differs from the manifest; use --refresh to re-download")
        return data
    data = fetch()
    if expected is not None and _sha256(data) != expected:
        raise RuntimeError(f"{path}: downloaded bytes do not match the manifest's sha256")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


NOTICES = DATASETS.parent / "THIRD_PARTY_NOTICES.md"


def write_notices(manifest: dict[str, Any]) -> None:
    """MIT and ISC require the copyright and permission notice to accompany copies.
    Every mutation case holds a copy (base/) or a one-line modification (head/) of a
    third-party file, so the license texts are reproduced verbatim here, offline,
    from the vendored license files."""
    parts = [
        "# Third-party notices\n\n"
        "The files under `evaluation/datasets/sources/`, and the `base/` and `head/` files of "
        "every case in `evaluation/cases/` whose directory name starts with `mut-`, are copies "
        "of (`base/`) or single-edit modifications of (`head/`) source files from the "
        "open-source projects below, redistributed under their licenses. Each license text is "
        "reproduced verbatim. Hand-made `fx-*` cases are project-authored.\n"
    ]
    for repo in manifest["repositories"]:
        text = (DATASETS / repo["license_file"]).read_text(encoding="utf-8").strip()
        files = ", ".join(f"`{e['path']}`" for e in repo["files"])
        parts.append(
            f"\n## {repo['id']} — {repo['license']}\n\n"
            f"Source: {repo['url']} at commit `{repo['commit']}`\n\nFiles used: {files}\n\n"
            f"```text\n{text}\n```\n"
        )
    NOTICES.write_bytes("".join(parts).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.datasets.fetch_sources")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--notices-only", action="store_true", help="regenerate THIRD_PARTY_NOTICES.md; no network"
    )
    args = parser.parse_args(argv)

    manifest: dict[str, Any] = json.loads(MANIFEST.read_bytes().decode("utf-8"))
    if args.notices_only:
        write_notices(manifest)
        return 0
    for repo in manifest["repositories"]:
        owner_repo = _owner_repo(repo["url"])
        license_file = DATASETS / "licenses" / f"{repo['id']}.LICENSE"
        data = _ensure(
            license_file,
            lambda r=repo, o=owner_repo: download(o, r["commit"], r["license_path"]),
            repo.get("license_sha256"),
            args.refresh,
        )
        repo["license_file"] = f"licenses/{repo['id']}.LICENSE"
        repo["license_sha256"] = _sha256(data)
        for entry in repo["files"]:
            vendored = f"sources/{repo['id']}/{entry['path']}"
            data = _ensure(
                DATASETS / vendored,
                lambda r=repo, e=entry, o=owner_repo: download(o, r["commit"], e["path"]),
                entry.get("sha256"),
                args.refresh,
            )
            entry["vendored_as"] = vendored
            entry["sha256"] = _sha256(data)
            entry["bytes"] = len(data)
            print(
                f"{repo['id']:<9} {entry['path']:<28} {len(data):>6} bytes  {entry['sha256'][:12]}",
                flush=True,
            )
    MANIFEST.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    write_notices(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
