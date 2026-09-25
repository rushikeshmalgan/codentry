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


def _load_optional(name: str) -> dict[str, Any] | None:
    path = DATASETS / name
    return json.loads(path.read_bytes().decode("utf-8")) if path.exists() else None


def notice_sections(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """One entry per redistributed open-source project, across all case families:
    `mut-*` (mutation), `bug-*` (BugsJS reversed fixes), `pr-*` (noise pull requests)."""
    sections = [
        {
            "title": f"{r['id']} — {r['license']}",
            "license_file": r["license_file"],
            "where": f"used by `mut-{r['id']}-*` cases and `datasets/sources/{r['id']}/`",
            "source": f"{r['url']} at commit `{r['commit']}`",
            "detail": "Files used: " + ", ".join(f"`{e['path']}`" for e in r["files"]),
        }
        for r in manifest["repositories"]
    ]
    bugs = _load_optional("bugsjs.json")
    for r in (bugs or {}).get("projects", []):
        if r["selected"]:
            sections.append(
                {
                    "title": f"BugsJS {r['bugsjs_name']} — {r['license']}",
                    "license_file": r["license_file"],
                    "where": "used by `bug-"
                    + r["id"]
                    + "-*` cases (base = fixed file, head = buggy file)",
                    "source": (
                        f"{r['url']} (BugsJS fork; bug tags), dataset {bugs['bug_dataset']['url']}"
                    ),
                    "detail": "Files used: "
                    + ", ".join(sorted({e["path"] for e in r["selected"]})),
                }
            )
    noise = _load_optional("noise_prs.json")
    for r in (noise or {}).get("repositories", []):
        if r["selected"]:
            sections.append(
                {
                    "title": f"{r['id']} (pull requests) — {r['license']}",
                    "license_file": r["license_file"],
                    "where": f"used by `pr-{r['id']}-*` cases "
                    "(base = before the merged pull request, "
                    "head = after)",
                    "source": f"{r['url']} at pinned commit `{r['pinned_commit']}`",
                    "detail": f"{len(r['selected'])} merged pull requests, "
                    "listed in datasets/noise_prs.json",
                }
            )
    return sections


def write_notices(manifest: dict[str, Any]) -> None:
    """MIT, ISC and similar licenses require the copyright and permission notice to
    accompany copies. Every `mut-*`, `bug-*` and `pr-*` case holds copies (or one-edit
    modifications) of third-party files, so the license texts are reproduced verbatim
    here, offline, from the vendored license files."""
    parts = [
        "# Third-party notices\n\n"
        "The files under `evaluation/datasets/sources/` and the `base/` and `head/` files of "
        "every case in `evaluation/cases/` whose directory name starts with `mut-`, `bug-` or "
        "`pr-` are copies of (`base/`), single-edit modifications of (`head/`), or historical "
        "versions of source files from the open-source projects below, redistributed under "
        "their licenses. Each license text is reproduced verbatim. Hand-made `fx-*` cases are "
        "project-authored.\n"
    ]
    for s in notice_sections(manifest):
        text = (DATASETS / s["license_file"]).read_bytes().decode("utf-8").strip()
        where = s["where"][0].upper() + s["where"][1:]
        parts.append(
            f"\n## {s['title']}\n\n{where}.\n\n"
            f"Source: {s['source']}\n\n{s['detail']}\n\n```text\n{text}\n```\n"
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
