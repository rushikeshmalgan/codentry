"""The committed real-defect corpus (BugsJS bugs, fixes reversed): provenance,
licenses, hashes, and — the key check — that each case's recorded ground truth
equals what `git diff` says the fix changed.

Offline: the only external program is `git diff --no-index` on committed files.
"""

import hashlib
import json
import subprocess

import pytest

from evaluation.case import line_count, load_case
from evaluation.datasets.bugsjs import (
    CASE_PREFIX,
    PROJECTS,
    STRATUM,
    head_ranges_from_diff,
)
from evaluation.tests.helpers import COMMITTED_CASES, REPO_ROOT

DATASETS = REPO_ROOT / "evaluation" / "datasets"
MANIFEST = json.loads((DATASETS / "bugsjs.json").read_bytes().decode("utf-8"))
BUGS = [(p, e) for p in MANIFEST["projects"] for e in p["selected"]]
BUG_DIRS = sorted(d for d in COMMITTED_CASES.glob(f"{CASE_PREFIX}*") if d.is_dir())
IDS = [e["case"] for _p, e in BUGS]


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_diff_head_ranges(base_path, head_path, head_text):
    proc = subprocess.run(
        ["git", "diff", "--no-index", "--no-renames", "-U0", "--", str(base_path), str(head_path)],
        capture_output=True, check=False, timeout=60,
    )
    assert proc.returncode in (0, 1), proc.stderr  # 1 = files differ
    return head_ranges_from_diff(proc.stdout.decode("utf-8", "replace"), line_count(head_text))


# ---- the corpus as a whole --------------------------------------------------
def test_there_are_at_least_20_real_defect_cases_from_at_least_3_projects():
    projects = {p["id"] for p, _e in BUGS}
    assert len(BUGS) >= 20 and len(projects) >= 3, (len(BUGS), projects)


def test_every_case_on_disk_is_in_the_manifest_and_vice_versa():
    assert sorted(d.name for d in BUG_DIRS) == sorted(IDS)


def test_the_manifest_states_its_limits_and_how_bugs_were_selected():
    text = " ".join(MANIFEST["threats"]).lower()
    for phrase in ("reversal is not a natural pull request", "contamination", "selection"):
        assert phrase in text, phrase
    assert MANIFEST["selection"]["criteria"] and MANIFEST["selection"]["seed"] is not None
    assert MANIFEST["bug_dataset"]["commit"] and len(MANIFEST["bug_dataset"]["commit"]) == 40
    for p in MANIFEST["projects"]:
        assert p["id"] in PROJECTS and p["excluded_by_reason"] is not None


@pytest.mark.parametrize("project", MANIFEST["projects"], ids=lambda p: p["id"])
def test_each_project_records_a_license_and_its_text(project):
    if not project["selected"]:
        pytest.skip("no bugs selected from this project")
    assert project["license"] in {"MIT", "CC0-1.0"}
    path = DATASETS / project["license_file"]
    assert sha256(path) == project["license_sha256"]
    text = path.read_text(encoding="utf-8")
    assert ("Permission is hereby granted" in text) if project["license"] == "MIT" else ("CC0" in text)


# ---- every case ----------------------------------------------------------------
@pytest.mark.parametrize("project, entry", BUGS, ids=IDS)
def test_case_is_valid_labeled_and_hashes_match_the_manifest(project, entry):
    case_dir = COMMITTED_CASES / entry["case"]
    case = load_case(case_dir)  # schema + range checks
    doc = json.loads((case_dir / "case.json").read_bytes())
    assert case.stratum == STRATUM and case.ground_truth_status == "labeled"
    assert doc["license"] == project["license"]
    assert doc["source"]["derivation"] == "reversed_fix"
    assert doc["source"]["base_sha"] == entry["fixed_commit"]  # base = FIXED
    assert doc["source"]["head_sha"] == entry["buggy_commit"]  # head = BUGGY
    assert sha256(case_dir / "case.json") == entry["sha256"]["case.json"]
    assert sha256(case_dir / "base" / entry["path"]) == entry["sha256"]["base"]
    assert sha256(case_dir / "head" / entry["path"]) == entry["sha256"]["head"]


@pytest.mark.parametrize("project, entry", BUGS, ids=IDS)
def test_reversal_diff_equals_the_recorded_fix_ranges(project, entry):
    """base = fixed file, head = buggy file, so the diff of base -> head is the fix undone,
    and its head-side hunks must be exactly the ground truth. Recomputed here with git."""
    case_dir = COMMITTED_CASES / entry["case"]
    case = load_case(case_dir)
    (file,) = case.inputs.files
    assert file.base_content != file.head_content
    from_git = git_diff_head_ranges(
        case_dir / "base" / file.path, case_dir / "head" / file.path, file.head_content
    )
    recorded = [(d.start_line, d.end_line) for d in case.ground_truth]
    assert from_git == recorded == [tuple(r) for r in entry["head_ranges"]]


@pytest.mark.parametrize("project, entry", BUGS, ids=IDS)
def test_all_locations_of_one_bug_share_a_group_so_recall_counts_the_bug_once(project, entry):
    case = load_case(COMMITTED_CASES / entry["case"])
    groups = {d.group for d in case.ground_truth}
    assert groups == {f"bugsjs-{project['id']}-{entry['bug']}"}


@pytest.mark.parametrize("project, entry", BUGS, ids=IDS)
def test_evidence_claims_match_what_the_manifest_recorded(project, entry):
    """A case may only claim an executable test if BugsJS recorded one; the other
    cases must say plainly that they rest on manual validation."""
    case = load_case(COMMITTED_CASES / entry["case"])
    methods = {m for d in case.ground_truth for m, _ref in d.verified_by}
    assert "dataset_annotation" in methods
    assert not methods - {"dataset_annotation", "executable_test"}  # never a model
    if entry["test_evidence"] == "recorded_run":
        assert entry["bug_revealing_tests"] and "executable_test" in methods
    else:
        assert entry["test_evidence"] == "none_recorded"
        assert not entry["bug_revealing_tests"] and "executable_test" not in methods


def test_how_many_cases_have_a_recorded_failing_test_is_stated_not_hidden():
    counts = {"recorded_run": 0, "none_recorded": 0}
    for _p, e in BUGS:
        counts[e["test_evidence"]] += 1
    assert sum(counts.values()) == len(BUGS)
    assert counts["recorded_run"] >= 1  # the corpus is not purely dataset-annotation
