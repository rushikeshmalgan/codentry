"""Recently merged pull requests, for measuring how much noise the static arm adds.

    python -m evaluation.datasets.noise_prs --work <cache-dir>

These cases have **no defect labels** (`ground_truth_status: unlabeled`): they exist
to measure findings per pull request, the `new` vs `existing` share, the duplicate
rate and identity stability on realistic changes — not recall or precision.

A "pull request" is derived from repository history alone (no API, no credentials):
starting at a pinned commit of the default branch, walk first-parent history and
take each commit whose subject ends in ``(#N)`` (a squash merge) or starts with
``Merge pull request #N``. Its change is *first parent -> that commit*, restricted to
analyzable JavaScript/TypeScript source. The selection is deterministic given the
pinned commit, so re-running reproduces it.

This is a one-time acquisition step (network: git fetch from GitHub). Tests verify
the written files offline against ``evaluation/datasets/noise_prs.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from evaluation.datasets.licensing import verify as verify_license

EVALUATION = Path(__file__).resolve().parents[1]
CASES = EVALUATION / "cases"
DATASETS = EVALUATION / "datasets"
MANIFEST = DATASETS / "noise_prs.json"
CASE_PREFIX = "pr-"
STRATUM = "noise:pr"

# Repositories, each pinned to a default-branch commit observed on 2026-09-26. Licenses
# were read from GitHub's license API (MIT for all three) and the texts are vendored.
REPOS: dict[str, dict[str, Any]] = {
    "fastify": {
        "url": "https://github.com/fastify/fastify",
        "pin": "e6860c59fcf46653d690bb5890b189732023d5b9",
        "license": "MIT",
        "take": 12,
    },
    "axios": {
        "url": "https://github.com/axios/axios",
        "pin": "961241f6c19798eff16b0869486c125430a17961",
        "license": "MIT",
        "take": 12,
    },
    "zod": {
        "url": "https://github.com/colinhacks/zod",
        "pin": "2bf7b0630d5378033e90bcee82cb32b0fe04628e",
        "license": "MIT",
        "take": 12,
    },
}
CRITERIA = {
    "merge_forms": "subject ends '(#N)' (squash) or starts 'Merge pull request #N'",
    "change": "first parent -> the merge/squash commit",
    "analyzable_files": "1 to 6 changed files ending .js/.jsx/.ts/.tsx "
    "(not .d.ts/.min.js, not under "
    "dist/ build/ node_modules/ vendor/ or generated locations)",
    "max_changed_lines": 300,
    "max_file_bytes": 60_000,
    "text": "UTF-8, no carriage returns in any selected file",
    "order": "most recent first, take the first N that qualify",
}
_ANALYZABLE = re.compile(r"\.(jsx?|tsx?)$", re.I)
_EXCLUDED = re.compile(
    r"(\.d\.ts$|\.min\.js$|(^|/)(dist|build|node_modules|vendor|coverage|\.git|generated|__snapshots__)/)",
    re.I,
)
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")
_MERGE = re.compile(r"^Merge pull request #(\d+)\b")


class NoiseError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str, text: bool = True, timeout: int = 900) -> Any:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False, timeout=timeout
    )
    if proc.returncode != 0:
        raise NoiseError(
            f"git {' '.join(args[:3])}: {proc.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return proc.stdout.decode("utf-8", "replace") if text else proc.stdout


def ensure_clone(work: Path, name: str, spec: dict[str, Any]) -> Path:
    """A bare, blob-less clone of the default branch (commits and trees, no file contents)."""
    repo = work / f"noise-{name}.git"
    if not repo.exists():
        proc = subprocess.run(
            [
                "git",
                "clone",
                "--bare",
                "--filter=blob:none",
                "--single-branch",
                "-q",
                f"{spec['url']}.git",
                str(repo),
            ],
            capture_output=True,
            timeout=1800,
            check=False,
        )
        if proc.returncode != 0:
            raise NoiseError(f"clone {name}: {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    if git(repo, "cat-file", "-t", spec["pin"]).strip() != "commit":
        raise NoiseError(f"{name}: pinned commit {spec['pin']} not found in the clone")
    return repo


def candidates(repo: Path, pin: str, limit: int = 400) -> list[tuple[str, int]]:
    """(commit, PR number) for pull-request merges on the first-parent path, newest first."""
    out = git(repo, "log", "--first-parent", f"--max-count={limit}", "--format=%H%x00%s", pin)
    found = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x00")
        m = _SQUASH.search(subject) or _MERGE.match(subject)
        if m:
            found.append((sha, int(m.group(1))))
    return found


def parse_changes(status_output: str) -> list[dict[str, str]]:
    changes = []
    for line in status_output.splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        if code == "R":
            changes.append({"status": "renamed", "previous_path": parts[1], "path": parts[2]})
        elif code == "A":
            changes.append({"status": "added", "path": parts[1]})
        elif code == "M":
            changes.append({"status": "modified", "path": parts[1]})
        elif code == "D":
            changes.append({"status": "removed", "path": parts[1]})
        else:  # copies, type changes: not representable, so the PR is not eligible
            changes.append({"status": "unsupported", "path": parts[-1]})
    return changes


def is_analyzable(path: str) -> bool:
    return bool(_ANALYZABLE.search(path)) and not _EXCLUDED.search(path)


def examine(repo: Path, sha: str, number: int) -> dict[str, Any]:
    parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()
    if len(parents) < 2:
        return {"reason": "no_parent"}
    base = parents[1]
    raw = git(repo, "diff", "--name-status", "-M", base, sha)
    changes = parse_changes(raw)
    if any(c["status"] == "unsupported" for c in changes):
        return {"reason": "unsupported_change_kind"}
    chosen = [
        c for c in changes if is_analyzable(c["path"]) or is_analyzable(c.get("previous_path", ""))
    ]
    if not 1 <= len(chosen) <= 6:
        return {"reason": "analyzable_file_count"}
    pathspec = sorted({p for c in chosen for p in (c["path"], c.get("previous_path")) if p})
    numstat = git(repo, "diff", "--numstat", "-M", base, sha, "--", *pathspec)
    changed_lines = 0
    for line in numstat.splitlines():
        added, deleted, _ = line.split("\t", 2)
        if added == "-":
            return {"reason": "binary"}
        changed_lines += int(added) + int(deleted)
    if changed_lines > CRITERIA["max_changed_lines"]:
        return {"reason": "too_many_changed_lines"}

    contents: list[dict[str, Any]] = []
    for c in chosen:
        entry = dict(c)
        for side, ref, path in (
            ("base", base, c.get("previous_path", c["path"])),
            ("head", sha, c["path"]),
        ):
            if (side == "base" and c["status"] == "added") or (
                side == "head" and c["status"] == "removed"
            ):
                entry[side] = None
                continue
            raw_bytes = git(repo, "show", f"{ref}:{path}", text=False)
            if len(raw_bytes) > CRITERIA["max_file_bytes"]:
                return {"reason": "file_too_large"}
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return {"reason": "not_utf8"}
            if "\r" in text:
                return {"reason": "carriage_returns"}
            entry[side] = text
        contents.append(entry)
    message = git(repo, "log", "-1", "--format=%s", sha).strip()
    return {
        "reason": None,
        "base": base,
        "head": sha,
        "subject": message,
        "changed_lines": changed_lines,
        "files": contents,
        "number": number,
    }


def case_document(repo_id: str, spec: dict[str, Any], pr: dict[str, Any]) -> dict[str, Any]:
    languages = {
        "typescript" if re.search(r"\.tsx?$", f["path"], re.I) else "javascript"
        for f in pr["files"]
    }
    files = []
    for f in pr["files"]:
        entry: dict[str, Any] = {"path": f["path"], "status": f["status"]}
        if f["status"] == "renamed":
            entry["previous_path"] = f["previous_path"]
        if f["base"] is not None:
            entry["base"] = f"base/{f.get('previous_path', f['path'])}"
        if f["head"] is not None:
            entry["head"] = f"head/{f['path']}"
        files.append(entry)
    return {
        "schema_version": 1,
        "id": f"{CASE_PREFIX}{repo_id}-{pr['number']}",
        "stratum": STRATUM,
        "language": "typescript" if "typescript" in languages else "javascript",
        "license": spec["license"],
        "source": {
            "kind": "repository",
            "url": spec["url"],
            "base_sha": pr["base"],
            "head_sha": pr["head"],
            "derivation": "pull_request",
            "pull_request": pr["number"],
        },
        "files": files,
        "ground_truth_status": "unlabeled",
        "ground_truth": [],
    }


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256(data)


def run(work: Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    for stale in CASES.glob(f"{CASE_PREFIX}*"):
        shutil.rmtree(stale)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "Recently merged pull requests without defect labels, for noise measurement.",
        "selection": {"criteria": CRITERIA},
        "threats": [
            "Recency: the pin is one moment in each repository's history; results describe "
            "these pull requests, not the projects.",
            "Three projects, one to two dozen small pull requests each: a small, clustered "
            "sample of well-maintained MIT-licensed libraries, not typical student code.",
            "Selection favors small changes to source files (1-6 files, <=300 changed lines); "
            "large or test-only pull requests are excluded.",
            "Derivation is from history (first parent -> merge/squash commit); it can differ "
            "from what a reviewer saw if the branch was rebased or amended before merging.",
            "No defect labels: findings on these cases say nothing about accuracy.",
        ],
        "repositories": [],
    }
    for name, spec in REPOS.items():
        repo = ensure_clone(work, name, spec)
        found = candidates(repo, spec["pin"])
        excluded: dict[str, int] = {}
        selected: list[dict[str, Any]] = []
        for sha, number in found:
            if len(selected) >= spec["take"]:
                break
            pr = examine(repo, sha, number)
            if pr["reason"]:
                excluded[pr["reason"]] = excluded.get(pr["reason"], 0) + 1
                continue
            doc = case_document(name, spec, pr)
            case_dir = CASES / doc["id"]
            shas: dict[str, Any] = {}
            for f in pr["files"]:
                if f["base"] is not None:
                    shas[f"base/{f.get('previous_path', f['path'])}"] = _write(
                        case_dir / "base" / f.get("previous_path", f["path"]), f["base"].encode()
                    )
                if f["head"] is not None:
                    shas[f"head/{f['path']}"] = _write(
                        case_dir / "head" / f["path"], f["head"].encode()
                    )
            shas["case.json"] = _write(
                case_dir / "case.json", (json.dumps(doc, indent=2) + "\n").encode()
            )
            selected.append(
                {
                    "case": doc["id"],
                    "pull_request": pr["number"],
                    "subject": pr["subject"],
                    "base_sha": pr["base"],
                    "head_sha": pr["head"],
                    "changed_lines": pr["changed_lines"],
                    "files": [f["path"] for f in pr["files"]],
                    "sha256": dict(sorted(shas.items())),
                }
            )
            print(
                f"  {doc['id']:<18} files={len(pr['files'])} lines={pr['changed_lines']:<4} "
                f"{pr['subject'][:60]}",
                flush=True,
            )
        license_text = b""
        for lic_name in ("LICENSE", "LICENSE.md", "license"):
            try:
                license_text = git(repo, "show", f"{spec['pin']}:{lic_name}", text=False)
                break
            except NoiseError:
                continue
        else:
            raise NoiseError(f"{name}: no license file at the pinned commit")
        license_file = f"licenses/noise-{name}.LICENSE"
        license_sha = _write(DATASETS / license_file, license_text)
        license_verified = verify_license(license_text.decode("utf-8"), spec["license"])
        manifest["repositories"].append(
            {
                "id": name,
                "url": spec["url"],
                "pinned_commit": spec["pin"],
                "license": spec["license"],
                "license_file": license_file,
                "license_sha256": license_sha,
                "license_verified": license_verified,
                "candidates_examined": len(found),
                "excluded_by_reason": dict(sorted(excluded.items())),
                "selected": selected,
            }
        )
        print(
            f"{name}: selected {len(selected)} of {len(found)} candidates; excluded {excluded}",
            flush=True,
        )
    MANIFEST.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.datasets.noise_prs")
    parser.add_argument("--work", type=Path, required=True, help="cache dir for partial clones")
    args = parser.parse_args(argv)
    try:
        run(args.work)
    except (NoiseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
