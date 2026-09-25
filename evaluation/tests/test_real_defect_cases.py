"""Integrity of the BugsJS real-defect cases (reversed fixes). Offline: no network,
no analysis tools, nothing from any project's test suite is executed."""

import hashlib
import json

import pytest

from evaluation.case import load_case
from evaluation.diffing import changed_head_ranges
from evaluation.tests.helpers import COMMITTED_CASES, REPO_ROOT

DATASETS = REPO_ROOT / "evaluation" / "datasets"
MANIFEST = json.loads((DATASETS / "bugsjs.json").read_bytes().decode("utf-8"))
ENTRIES = [(p, e) for p in MANIFEST["projects"] for e in p["selected"]]
IDS = [e["case"] for _, e in ENTRIES]
PERMISSIVE = {"MIT", "CC0-1.0", "ISC", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"}


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_there_are_at_least_20_cases_from_at_least_3_projects():
    assert len(ENTRIES) >= 20
    assert len({p["id"] for p, _ in ENTRIES}) >= 3
    assert len(set(IDS)) == len(IDS)


def test_no_case_directory_exists_that_the_manifest_does_not_list():
    on_disk = sorted(p.name for p in COMMITTED_CASES.glob("bug-*") if p.is_dir())
    assert on_disk == sorted(IDS)


@pytest.mark.parametrize("project", MANIFEST["projects"], ids=lambda p: p["id"])
def test_each_project_records_a_permissive_license_and_its_vendored_text(project):
    if not project["selected"]:
        pytest.skip("no cases selected from this project")
    assert project["license"] in PERMISSIVE
    text_path = DATASETS / project["license_file"]
    assert sha(text_path) == project["license_sha256"]
    assert text_path.read_bytes().strip(), "license text is empty"


@pytest.mark.parametrize("project, entry", ENTRIES, ids=IDS)
def test_every_file_of_a_case_matches_the_hash_in_the_manifest(project, entry):
    case_dir = COMMITTED_CASES / entry["case"]
    assert sha(case_dir / "case.json") == entry["sha256"]["case.json"]
    assert sha(case_dir / "base" / entry["path"]) == entry["sha256"]["base"]
    assert sha(case_dir / "head" / entry["path"]) == entry["sha256"]["head"]


@pytest.fixture(scope="module")
def cases():
    return {cid: load_case(COMMITTED_CASES / cid) for cid in IDS}


def test_every_case_validates_and_is_labeled_real_defect_ground_truth(cases):
    for cid, case in cases.items():
        assert case.stratum == "real:bugsjs", cid
        assert case.ground_truth_status == "labeled", cid
        assert case.ground_truth, cid
        for defect in case.ground_truth:
            assert defect.provenance == "real_defect", cid
            assert defect.kind == "correctness", cid


def test_reversal_produces_base_and_head_whose_diff_equals_the_recorded_fix_ranges(cases):
    for project, entry in ENTRIES:
        case = cases[entry["case"]]
        (file,) = case.inputs.files
        ranges = changed_head_ranges(file.base_content, file.head_content)
        assert ranges == [tuple(r) for r in entry["head_ranges"]], entry["case"]
        assert ranges == [(d.start_line, d.end_line) for d in case.ground_truth], entry["case"]


def test_base_is_the_fixed_revision_and_head_the_buggy_one(cases):
    for project, entry in ENTRIES:
        doc = json.loads((COMMITTED_CASES / entry["case"] / "case.json").read_bytes())
        source = doc["source"]
        assert source["derivation"] == "reversed_fix"
        assert source["base_sha"] == entry["fixed_commit"] != source["head_sha"]
        assert source["head_sha"] == entry["buggy_commit"]
        n = entry["bug"]
        assert (source["base_ref"], source["head_ref"]) == (f"Bug-{n}-fix", f"Bug-{n}")
        assert doc["license"] == project["license"]


def test_all_locations_of_one_bug_share_a_group_so_recall_counts_the_bug_once(cases):
    for cid, case in cases.items():
        assert len({d.group for d in case.ground_truth}) == 1, cid
    assert any(len(c.ground_truth) > 1 for c in cases.values()), "expected some multi-hunk fixes"


def test_evidence_level_is_stated_honestly_per_case(cases):
    """`executable_test` appears only where the dataset recorded test results, and every
    case keeps the dataset's manual validation as its baseline evidence."""
    for project, entry in ENTRIES:
        methods = {m for d in cases[entry["case"]].ground_truth for m, _ in d.verified_by}
        assert "dataset_annotation" in methods, entry["case"]
        if entry["test_evidence"] == "recorded_run":
            assert "executable_test" in methods and entry["bug_revealing_tests"], entry["case"]
        else:
            assert "executable_test" not in methods and entry["bug_revealing_tests"] == []
    evidence = {e["test_evidence"] for _, e in ENTRIES}
    assert evidence == {"recorded_run", "none_recorded"}, "both evidence levels are present"


def test_the_manifest_states_its_limits_and_pins_the_dataset():
    threats = " ".join(MANIFEST["threats"])
    for phrase in ("Reversal is not a natural pull request", "Contamination", "RECORDED test run"):
        assert phrase in threats
    assert len(MANIFEST["bug_dataset"]["commit"]) == 40
    assert MANIFEST["selection"]["criteria"]["max_hunks"] == 3
    for project in MANIFEST["projects"]:
        assert "excluded_by_reason" in project and project["eligible"] >= len(project["selected"])


def test_no_test_file_or_project_code_is_executed_or_vendored():
    """Cases contain a single source file each; nothing from a project's test suite."""
    for cid in IDS:
        files = [p for p in (COMMITTED_CASES / cid).rglob("*") if p.is_file()]
        assert len(files) == 3, (cid, files)  # case.json + base/<file> + head/<file>
