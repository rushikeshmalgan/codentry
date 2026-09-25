"""Real-defect cases from BugsJS, built by reversing each bug's fix.

    python -m evaluation.datasets.bugsjs --work <cache-dir> --bug-dataset <bug-dataset-clone>

BugsJS (Gyimesi et al., ICST 2019; survey ref [54]) is a benchmark of manually
validated bugs from real Node.js projects. For each bug it publishes git tags in
a fork of the project: ``Bug-N`` is the BUGGY revision and ``Bug-N-fix`` is that
revision plus the dataset authors' cleaned fix (no tests, no changelog). Its
``bug-dataset`` repository records, per bug, the test results on the buggy
revision and on the buggy revision plus the fix's new tests.

A case here is the fix **reversed**: ``base`` = the fixed file, ``head`` = the
buggy file, so the "pull request" reintroduces the bug and the ground truth is
where the fix changed the code (head-side line ranges, one location per hunk, all
in one defect group). That is not a natural pull request, and these are popular
projects likely to be in a model's training data; both limits are recorded in
the manifest.

This is a one-time acquisition step (network: git fetch from GitHub, no API, no
credentials). It writes case directories under ``evaluation/cases/bug-*`` and
``evaluation/datasets/bugsjs.json`` (hashes of every file it wrote); tests verify
those files offline. Nothing here executes project code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from evaluation.datasets.licensing import verify as verify_license
from evaluation.diffing import changed_head_ranges

EVALUATION = Path(__file__).resolve().parents[1]
CASES = EVALUATION / "cases"
DATASETS = EVALUATION / "datasets"
MANIFEST = DATASETS / "bugsjs.json"
CASE_PREFIX = "bug-"
STRATUM = "real:bugsjs"

BUG_DATASET_URL = "https://github.com/BugsJS/bug-dataset"
BUG_DATASET_COMMIT = "7abbad3e4df12cd5294110bb5db11b7d5bc758a6"
SELECTION_SEED = 20260925

# name in bug-dataset, bugs in the dataset, how many to sample. Licenses were checked
# on 2026-09-25 (GitHub license API; texts vendored and read). Pencilblue is excluded:
# GPL-3.0, unlike every other source in this corpus. Mongoose (no license file found by
# GitHub's API) and Node-redis are not used. In this bug-dataset snapshot the archives of
# Karma, ESLint, Mongoose and Node-redis carry no test_results.json (only static-metric
# CSVs), so recorded failing-test ids exist only for Express, Hexo, Hessian.js, Bower and
# Shields; for the others the ground truth rests on BugsJS's own manual validation.
PROJECTS: dict[str, dict[str, Any]] = {
    "express": {"name": "Express", "bugs": 27, "take": 8, "license": "MIT"},
    "hexo": {"name": "Hexo", "bugs": 12, "take": 6, "license": "MIT"},
    "hessian.js": {"name": "Hessian.js", "bugs": 9, "take": 4, "license": "MIT"},
    "bower": {"name": "Bower", "bugs": 3, "take": 3, "license": "MIT"},
    "shields": {"name": "Shields", "bugs": 4, "take": 4, "license": "CC0-1.0"},
    "karma": {"name": "Karma", "bugs": 22, "take": 6, "license": "MIT"},
    "eslint": {"name": "Eslint", "bugs": 333, "take": 6, "license": "MIT"},
}
CRITERIA = {
    "changed_files": (
        "the cleaned fix changes exactly one file, a JavaScript source file (not a test)"
    ),
    "max_hunks": 3,
    "max_changed_head_lines": 20,
    "recorded_tests": (
        "where the dataset records test results: at least one test fails with the fix's tests "
        "added but not on the buggy revision (a bug whose recorded results show none is excluded); "
        "where it records none, the bug is kept and its evidence is BugsJS's manual validation only"
    ),
    "diff_agreement": "git's diff and the harness's difflib diff give the same head-side hunks",
    "text": "UTF-8, no carriage returns",
}
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|fixtures?|docs?|benchmarks?)/", re.I)


class ImportError_(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str, text: bool = True) -> Any:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False, timeout=900
    )
    if proc.returncode != 0:
        raise ImportError_(
            f"git {' '.join(args[:3])}: {proc.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return proc.stdout.decode("utf-8", "replace") if text else proc.stdout


def ensure_repo(work: Path, project: str, bugs: int) -> Path:
    """A bare, blob-less partial clone holding just the Bug-N and Bug-N-fix tags."""
    repo = work / f"bugsjs-{project}.git"
    if not repo.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
        git(repo, "remote", "add", "origin", f"https://github.com/BugsJS/{project}.git")
        git(repo, "config", "remote.origin.promisor", "true")
        git(repo, "config", "remote.origin.partialclonefilter", "blob:none")
    specs = []
    for n in range(1, bugs + 1):
        specs += [
            f"+refs/tags/Bug-{n}:refs/tags/Bug-{n}",
            f"+refs/tags/Bug-{n}-fix:refs/tags/Bug-{n}-fix",
        ]
    git(repo, "fetch", "-q", "--filter=blob:none", "--depth=1", "origin", *specs)
    return repo


def is_source(path: str) -> bool:
    low = path.lower()
    return (
        low.endswith(".js")
        and not _TEST_PATH.search(low)
        and ".test." not in low
        and ".spec." not in low
        and "node_modules/" not in low
    )


def head_ranges_from_diff(diff: str, head_lines: int) -> list[tuple[int, int]]:
    """Head-side ranges from `git diff -U0` output, one per hunk. Same deletion
    convention as evaluation.diffing: a pure deletion (no head lines) is located at
    the line now sitting at that point, clamped to the file. Pure and offline: the
    tests recompute it with `git diff --no-index` on the committed base/head files."""
    ranges = []
    for start, count in _HUNK.findall(diff):
        start_i = int(start)
        count_i = 1 if count == "" else int(count)
        if count_i == 0:
            line = min(start_i + 1, max(head_lines, 1))
            ranges.append((line, line))
        else:
            ranges.append((start_i, start_i + count_i - 1))
    return ranges


def git_head_ranges(repo: Path, base_ref: str, head_ref: str, path: str, head_lines: int):
    """Head-side hunk ranges according to git (-U0) between two refs of `repo`."""
    diff = git(repo, "diff", "-U0", "--no-renames", base_ref, head_ref, "--", path)
    return head_ranges_from_diff(diff, head_lines)


class NoTestResults(ImportError_):
    pass


def bug_revealing_tests(bug_dataset: Path, name: str, n: int) -> list[str]:
    archive = bug_dataset / "Projects" / name / f"{name}-{n}.zip"
    with zipfile.ZipFile(archive) as outer:
        names = set(outer.namelist())

        def failures(version: str) -> set[str]:
            entry = f"{version}/test_results.json.zip"
            if entry not in names:
                raise NoTestResults(f"{name}-{n}: missing {entry}")
            inner = zipfile.ZipFile(io.BytesIO(outer.read(entry)))
            members = [m for m in inner.namelist() if not m.endswith("/")]
            try:
                data = json.loads(inner.read(members[0]).decode("utf-8-sig", "replace"))
                return {f.get("fullTitle") or f.get("title") for f in data.get("failures", [])}
            except (IndexError, ValueError, AttributeError) as exc:
                raise NoTestResults(
                    f"{name}-{n}: unusable {entry} ({exc.__class__.__name__})"
                ) from exc

        return sorted(failures("only_test_changes") - failures("buggy"))


def bug_categories(bug_dataset: Path, name: str) -> dict[int, str]:
    path = bug_dataset / "Projects" / name / f"{name}_bugs.csv"
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")), delimiter=";")
    return {int(r["ID"]): r.get("Bug category", "").strip() for r in rows}


def examine(repo: Path, bug_dataset: Path, project: str, name: str, n: int) -> dict[str, Any]:
    """Everything needed to decide on and build one case; `reason` set if excluded."""
    head_ref, base_ref = f"Bug-{n}", f"Bug-{n}-fix"
    try:
        status = git(repo, "diff", "--name-status", "--no-renames", head_ref, base_ref)
    except ImportError_:
        return {"n": n, "reason": "tags_missing"}
    changed = [line.split("\t") for line in status.splitlines() if line.strip()]
    if len(changed) != 1 or changed[0][0] != "M" or not is_source(changed[0][1]):
        return {"n": n, "reason": "not_a_single_modified_source_file"}
    path = changed[0][1]
    raw_base = git(repo, "show", f"{base_ref}:{path}", text=False)
    raw_head = git(repo, "show", f"{head_ref}:{path}", text=False)
    try:
        base, head = raw_base.decode("utf-8"), raw_head.decode("utf-8")
    except UnicodeDecodeError:
        return {"n": n, "reason": "not_utf8"}
    if "\r" in base or "\r" in head:
        return {"n": n, "reason": "carriage_returns"}
    head_lines = head.count("\n") + (0 if head.endswith("\n") or not head else 1)
    ranges = changed_head_ranges(base, head)
    if ranges != git_head_ranges(repo, base_ref, head_ref, path, head_lines):
        return {"n": n, "reason": "diff_disagreement"}
    if not ranges or len(ranges) > CRITERIA["max_hunks"]:
        return {"n": n, "reason": "too_many_hunks"}
    if sum(e - s + 1 for s, e in ranges) > CRITERIA["max_changed_head_lines"]:
        return {"n": n, "reason": "too_many_changed_lines"}
    tests: list[str] | None
    try:
        tests = bug_revealing_tests(bug_dataset, name, n)
    except NoTestResults:
        tests = None  # the dataset records no test results for this bug: evidence is weaker
    if tests is not None and not tests:
        return {"n": n, "reason": "recorded_results_show_no_bug_revealing_test"}
    return {
        "n": n,
        "reason": None,
        "path": path,
        "base": base,
        "head": head,
        "ranges": ranges,
        "tests": tests,
        "base_sha": git(repo, "rev-parse", f"{base_ref}^{{commit}}").strip(),
        "head_sha": git(repo, "rev-parse", f"{head_ref}^{{commit}}").strip(),
    }


def case_document(
    project: str, name: str, license_id: str, bug: dict, category: str
) -> dict[str, Any]:
    cid = f"{CASE_PREFIX}{project}-{bug['n']}"
    verified_by = [
        {
            "method": "dataset_annotation",
            "ref": f"BugsJS {name}-{bug['n']}: manually validated bug (Gyimesi et al., ICST 2019)",
        }
    ]
    if bug["tests"]:
        tests = "; ".join(bug["tests"])
        if len(tests) > 300:
            tests = tests[:297] + "..."
        verified_by.append(
            {
                "method": "executable_test",
                "ref": "BugsJS recorded run (not re-run here): fails with the fix's tests, "
                f"not on the buggy revision: {tests}",
            }
        )
    group = f"bugsjs-{project}-{bug['n']}"
    defects = [
        {
            "file": bug["path"],
            "start_line": start,
            "end_line": end,
            "kind": "correctness",
            "provenance": "real_defect",
            "verified_by": verified_by,
            "group": group,
            "description": (
                f"Location {i + 1} of {len(bug['ranges'])} changed by the fix of "
                f"BugsJS {name}-{bug['n']}"
                + (f" (category: {category})" if category else "")
                + "."
            )[:500],
        }
        for i, (start, end) in enumerate(bug["ranges"])
    ]
    return {
        "schema_version": 1,
        "id": cid,
        "stratum": STRATUM,
        "language": "javascript",
        "license": license_id,
        "source": {
            "kind": "repository",
            "url": f"https://github.com/BugsJS/{project}",
            "base_sha": bug["base_sha"],
            "head_sha": bug["head_sha"],
            "derivation": "reversed_fix",
            "base_ref": f"Bug-{bug['n']}-fix",
            "head_ref": f"Bug-{bug['n']}",
        },
        "files": [
            {
                "path": bug["path"],
                "status": "modified",
                "base": f"base/{bug['path']}",
                "head": f"head/{bug['path']}",
            }
        ],
        "ground_truth_status": "labeled",
        "ground_truth": defects,
    }


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256(data)


def run(work: Path, bug_dataset: Path) -> dict[str, Any]:
    commit = git(bug_dataset, "rev-parse", "HEAD").strip()
    if commit != BUG_DATASET_COMMIT:
        raise ImportError_(f"bug-dataset is at {commit}, expected {BUG_DATASET_COMMIT}")
    work.mkdir(parents=True, exist_ok=True)
    for stale in CASES.glob(f"{CASE_PREFIX}*"):
        shutil.rmtree(stale)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "purpose": (
            "Real-defect cases built by reversing BugsJS fixes "
            "(base = fixed file, head = buggy file)."
        ),
        "bug_dataset": {"url": BUG_DATASET_URL, "commit": BUG_DATASET_COMMIT},
        "selection": {
            "seed": SELECTION_SEED,
            "criteria": CRITERIA,
            "method": "per project: every bug meeting the criteria, then a seeded sample",
        },
        "threats": [
            "Reversal is not a natural pull request: the 'change' is a fix undone, so its shape "
            "(size, what surrounds it) differs from how bugs are really introduced.",
            "Contamination: Express, Karma, Hexo and ESLint are popular public projects, "
            "and BugsJS "
            "is public; a language model may have seen both the code and the fixes.",
            "Selection: only small, single-file, JavaScript-source fixes (see criteria), which "
            "favors localized bugs.",
            "Executable evidence is BugsJS's RECORDED test run, not a run by this project (no "
            "project test suite was executed here). For Karma and ESLint the dataset snapshot "
            "records no test results, so those cases rest on BugsJS's manual validation alone; "
            "each case says which (see test_evidence).",
            "Ground truth is where the fix changed code; a finding elsewhere that also points at "
            "the bug is scored as unmatched.",
        ],
        "projects": [],
    }
    rng = random.Random(SELECTION_SEED)
    for project, spec in PROJECTS.items():
        repo = ensure_repo(work, project, spec["bugs"])
        categories = bug_categories(bug_dataset, spec["name"])
        examined = [
            examine(repo, bug_dataset, project, spec["name"], n) for n in range(1, spec["bugs"] + 1)
        ]
        eligible = [b for b in examined if b["reason"] is None]
        excluded: dict[str, int] = {}
        for b in examined:
            if b["reason"]:
                excluded[b["reason"]] = excluded.get(b["reason"], 0) + 1
        chosen = sorted(
            rng.sample(eligible, min(spec["take"], len(eligible))), key=lambda b: b["n"]
        )

        license_text = b""
        if chosen:
            ref = f"Bug-{chosen[0]['n']}"
            for name in ("LICENSE", "LICENSE.md", "License", "license"):
                try:
                    license_text = git(repo, "show", f"{ref}:{name}", text=False)
                    break
                except ImportError_:
                    continue
            else:
                raise ImportError_(f"{project}: no LICENSE file found at {ref}")
        license_file = f"licenses/bugsjs-{project}.LICENSE"
        license_sha = _write(DATASETS / license_file, license_text)
        license_verified = (
            verify_license(license_text.decode("utf-8"), spec["license"]) if chosen else ""
        )
        entries = []
        for bug in chosen:
            doc = case_document(
                project, spec["name"], spec["license"], bug, categories.get(bug["n"], "")
            )
            case_dir = CASES / doc["id"]
            base_sha = _write(case_dir / "base" / bug["path"], bug["base"].encode("utf-8"))
            head_sha = _write(case_dir / "head" / bug["path"], bug["head"].encode("utf-8"))
            doc_sha = _write(
                case_dir / "case.json", (json.dumps(doc, indent=2) + "\n").encode("utf-8")
            )
            entries.append(
                {
                    "bug": bug["n"],
                    "case": doc["id"],
                    "path": bug["path"],
                    "buggy_commit": bug["head_sha"],
                    "fixed_commit": bug["base_sha"],
                    "head_ranges": [list(r) for r in bug["ranges"]],
                    "test_evidence": "recorded_run" if bug["tests"] else "none_recorded",
                    "bug_revealing_tests": bug["tests"] or [],
                    "category": categories.get(bug["n"], ""),
                    "sha256": {"case.json": doc_sha, "base": base_sha, "head": head_sha},
                }
            )
            print(
                f"  {doc['id']:<22} {bug['path']:<42} hunks={len(bug['ranges'])} "
                f"tests={len(bug['tests']) if bug['tests'] else 'none recorded'}",
                flush=True,
            )
        manifest["projects"].append(
            {
                "id": project,
                "bugsjs_name": spec["name"],
                "url": f"https://github.com/BugsJS/{project}",
                "license": spec["license"],
                "license_file": license_file,
                "license_sha256": license_sha,
                "license_verified": license_verified,
                "bugs_in_dataset": spec["bugs"],
                "eligible": len(eligible),
                "excluded_by_reason": dict(sorted(excluded.items())),
                "selected": entries,
            }
        )
        print(
            f"{project}: {len(eligible)} eligible of {spec['bugs']}, selected {len(entries)}, "
            f"excluded {excluded}",
            flush=True,
        )
    MANIFEST.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.datasets.bugsjs")
    parser.add_argument("--work", type=Path, required=True, help="cache dir for partial clones")
    parser.add_argument(
        "--bug-dataset",
        type=Path,
        required=True,
        help=f"a clone of {BUG_DATASET_URL} at {BUG_DATASET_COMMIT}",
    )
    args = parser.parse_args(argv)
    try:
        run(args.work, args.bug_dataset)
    except (ImportError_, OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
