"""Integrity of the noise-measurement pull-request cases. Offline; no tools run."""

import hashlib
import json

import pytest

from evaluation.case import load_case
from evaluation.tests.helpers import COMMITTED_CASES, REPO_ROOT

DATASETS = REPO_ROOT / "evaluation" / "datasets"
MANIFEST = json.loads((DATASETS / "noise_prs.json").read_bytes().decode("utf-8"))
ENTRIES = [(r, e) for r in MANIFEST["repositories"] for e in r["selected"]]
IDS = [e["case"] for _, e in ENTRIES]


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_there_are_at_least_30_pull_requests_from_at_least_3_repositories():
    assert len(ENTRIES) >= 30
    assert len({r["id"] for r, _ in ENTRIES}) >= 3
    assert len(set(IDS)) == len(IDS)


def test_no_pr_case_directory_exists_that_the_manifest_does_not_list():
    on_disk = sorted(p.name for p in COMMITTED_CASES.glob("pr-*") if p.is_dir())
    assert on_disk == sorted(IDS)


@pytest.mark.parametrize("repo", MANIFEST["repositories"], ids=lambda r: r["id"])
def test_each_repository_records_a_pinned_commit_and_its_license_text(repo):
    assert len(repo["pinned_commit"]) == 40 and repo["license"] == "MIT"
    assert sha(DATASETS / repo["license_file"]) == repo["license_sha256"]


@pytest.mark.parametrize("repo, entry", ENTRIES, ids=IDS)
def test_every_file_of_a_case_matches_the_hash_in_the_manifest(repo, entry):
    case_dir = COMMITTED_CASES / entry["case"]
    listed = {p.relative_to(case_dir).as_posix() for p in case_dir.rglob("*") if p.is_file()}
    assert listed == set(entry["sha256"])
    for relative, digest in entry["sha256"].items():
        assert sha(case_dir / relative) == digest, relative


@pytest.fixture(scope="module")
def cases():
    return {cid: load_case(COMMITTED_CASES / cid) for cid in IDS}


def test_pull_request_cases_are_unlabeled_by_construction(cases):
    for cid, case in cases.items():
        assert case.stratum == "noise:pr", cid
        assert case.ground_truth_status == "unlabeled", cid
        assert case.ground_truth == (), cid


def test_pull_request_cases_are_small_and_well_formed(cases):
    for repo, entry in ENTRIES:
        case = cases[entry["case"]]
        assert 1 <= len(case.inputs.files) <= 6
        assert entry["changed_lines"] <= MANIFEST["selection"]["criteria"]["max_changed_lines"]
        doc = json.loads((COMMITTED_CASES / entry["case"] / "case.json").read_bytes())
        source = doc["source"]
        assert source["derivation"] == "pull_request"
        assert source["pull_request"] == entry["pull_request"]
        assert source["base_sha"] != source["head_sha"]
        assert (source["base_sha"], source["head_sha"]) == (entry["base_sha"], entry["head_sha"])
        assert doc["license"] == repo["license"]


def test_file_statuses_agree_with_their_contents(cases):
    statuses = set()
    for case in cases.values():
        for f in case.inputs.files:
            statuses.add(f.status)
            assert (f.base_content is None) == (f.status == "added")
            assert (f.head_content is None) == (f.status == "removed")
            assert (f.previous_path is not None) == (f.status == "renamed")
    assert {"modified"} <= statuses


def test_the_manifest_states_its_limits():
    threats = " ".join(MANIFEST["threats"])
    for phrase in ("Recency", "No defect labels", "small, clustered sample"):
        assert phrase in threats
