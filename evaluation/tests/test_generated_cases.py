"""Integrity of the committed mutation corpus: the dataset manifest, the licenses,
every generated case, and full regeneration.

Offline apart from the local Node parser; no analysis tools run here.
"""

import hashlib
import json
from collections import Counter

import pytest

from evaluation.case import load_case
from evaluation.generators.build_cases import (
    CASE_PREFIX,
    DATASETS,
    DEFAULT_MANIFEST,
    load_manifest,
    verify,
)
from evaluation.generators.mutate import (
    GENERATOR_ID,
    INJECTION_NAMES,
    LOGIC_OPERATORS,
    STRATUM_LOGIC,
    STRATUM_RULE_ALIGNED,
    diff_head_range,
    run_helper,
    typescript_version,
)
from evaluation.tests.helpers import COMMITTED_CASES, REPO_ROOT

MANIFEST = load_manifest()
REDISTRIBUTABLE = {"MIT", "ISC", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"}
FILES = [(repo, entry) for repo in MANIFEST["repositories"] for entry in repo["files"]]
MUTATION_DIRS = sorted(p for p in COMMITTED_CASES.glob(f"{CASE_PREFIX}*") if p.is_dir())


@pytest.fixture(scope="module")
def cases():
    return {d.name: load_case(d) for d in MUTATION_DIRS}


@pytest.fixture(scope="module")
def documents():
    return {d.name: json.loads((d / "case.json").read_bytes()) for d in MUTATION_DIRS}


# ---- dataset manifest and licenses -----------------------------------------
def test_the_manifest_has_enough_repositories_and_files():
    assert len(MANIFEST["repositories"]) >= 4
    assert len(FILES) >= 12
    ids = [r["id"] for r in MANIFEST["repositories"]]
    assert len(set(ids)) == len(ids)
    for repo in MANIFEST["repositories"]:
        slugs = [e["slug"] for e in repo["files"]]
        assert len(set(slugs)) == len(slugs), repo["id"]


@pytest.mark.parametrize("repo", MANIFEST["repositories"], ids=lambda r: r["id"])
def test_every_repository_records_a_redistributable_license_and_its_text(repo):
    assert repo["license"] in REDISTRIBUTABLE
    assert repo["commit"] and len(repo["commit"]) == 40
    text_path = DATASETS / repo["license_file"]
    data = text_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == repo["license_sha256"]
    text = data.decode("utf-8")
    assert "Permission" in text  # every accepted license opens with a grant of permission
    assert repo["license_verified"].strip(), "say how the license was checked"


def test_third_party_notices_reproduce_every_license_text_verbatim():
    # normalize line endings: this file is not pinned by .gitattributes, so a Windows
    # checkout with core.autocrlf=true may hold it as CRLF
    notices = (REPO_ROOT / "evaluation" / "THIRD_PARTY_NOTICES.md").read_bytes().decode("utf-8")
    notices = notices.replace("\r\n", "\n")
    for repo in MANIFEST["repositories"]:
        assert repo["url"] in notices
    # every vendored license text (mutation sources, BugsJS projects, noise repositories)
    licenses = sorted((DATASETS / "licenses").glob("*.LICENSE"))
    assert len(licenses) >= 17
    for path in licenses:
        assert path.read_bytes().decode("utf-8").strip() in notices, path.name


def test_every_vendored_license_text_is_one_of_the_accepted_licenses():
    """The programmatic check the importers apply, re-applied to what is committed."""
    from evaluation.datasets.licensing import classify

    for path in sorted((DATASETS / "licenses").glob("*.LICENSE")):
        assert classify(path.read_bytes().decode("utf-8")) in {"MIT", "ISC", "CC0-1.0"}, path.name


@pytest.mark.parametrize(
    "repo, entry", FILES, ids=[f"{r['id']}:{e['path']}" for r, e in FILES]
)
def test_vendored_sources_match_the_hash_and_size_in_the_manifest(repo, entry):
    data = (DATASETS / entry["vendored_as"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert len(data) == entry["bytes"]
    assert b"\r" not in data and entry["language"] in {"javascript", "typescript"}


def test_the_manifest_pins_the_typescript_version_actually_in_use():
    assert MANIFEST["generation"]["typescript"] == typescript_version()
    assert MANIFEST["generation"]["generator"] == GENERATOR_ID


# ---- the committed cases ---------------------------------------------------
def test_there_are_at_least_120_logic_mutants_and_rule_aligned_ones_are_a_separate_stratum(cases):
    strata = Counter(c.stratum for c in cases.values())
    assert strata[STRATUM_LOGIC] >= 120, strata
    assert strata[STRATUM_RULE_ALIGNED] >= 1
    assert set(strata) == {STRATUM_LOGIC, STRATUM_RULE_ALIGNED}


def test_every_generated_case_validates_against_the_schema_and_loads(cases):
    assert cases, "no mutation cases committed"
    for case in cases.values():
        assert len(case.ground_truth) == 1
        assert case.ground_truth[0].provenance == "mutation"


def test_case_metadata_agrees_with_the_manifest(documents):
    by_id = {r["id"]: r for r in MANIFEST["repositories"]}
    for cid, doc in documents.items():
        repo_id = cid.removeprefix(CASE_PREFIX).split("-")[0]
        repo = by_id[repo_id]
        origin = doc["source"]["origin"]
        assert doc["license"] == repo["license"], cid
        assert (origin["url"], origin["commit"]) == (repo["url"], repo["commit"]), cid
        entry = next(e for e in repo["files"] if e["path"] == origin["path"])
        assert doc["language"] == entry["language"], cid
        assert doc["source"]["kind"] == "generated" and doc["source"]["seed"] >= 0


def test_the_base_of_every_case_is_the_vendored_original_byte_for_byte(documents):
    by_path = {(r["id"], e["path"]): e for r, e in FILES}
    for cid, doc in documents.items():
        repo_id = cid.removeprefix(CASE_PREFIX).split("-")[0]
        path = doc["source"]["origin"]["path"]
        original = (DATASETS / by_path[(repo_id, path)]["vendored_as"]).read_bytes()
        assert (COMMITTED_CASES / cid / "base" / path).read_bytes() == original, cid


def test_ground_truth_range_equals_the_diff_range_in_every_committed_case(cases):
    for cid, case in cases.items():
        (file,) = case.inputs.files
        defect = case.ground_truth[0]
        assert diff_head_range(file.base_content, file.head_content) == (
            defect.start_line,
            defect.end_line,
        ), cid


def test_every_committed_mutant_parses(cases):
    items = [
        {"name": cid, "filename": case.inputs.files[0].path, "text": case.inputs.files[0].head_content}
        for cid, case in cases.items()
    ]
    results = run_helper("check", items)["results"]
    assert [r["name"] for r in results if not r["ok"]] == []


def test_operator_metadata_is_consistent_with_the_stratum(documents):
    for cid, doc in documents.items():
        operator = doc["source"]["generator"].split(":", 1)[1]
        defect = doc["ground_truth"][0]
        if doc["stratum"] == STRATUM_LOGIC:
            assert operator in LOGIC_OPERATORS and defect["kind"] == "logic", cid
            assert defect["equivalence"] == "unchecked", cid
        else:
            assert operator in INJECTION_NAMES and defect["kind"] == "security", cid
            assert "equivalence" not in defect, cid
        assert defect["verified_by"] == [{"method": "construction", "ref": f"{GENERATOR_ID}:{operator}"}]


def test_logic_mutants_are_spread_over_the_operators_and_files(documents):
    logic = [d for d in documents.values() if d["stratum"] == STRATUM_LOGIC]
    operators = Counter(d["source"]["generator"].split(":", 1)[1] for d in logic)
    assert set(operators) == set(LOGIC_OPERATORS), operators  # all eight operators are exercised
    files = Counter(d["source"]["origin"]["path"] + d["source"]["origin"]["commit"] for d in logic)
    assert len(files) >= 12
    assert max(files.values()) <= 2 * min(files.values()) + 4  # no file dominates


def test_regenerating_from_the_seeds_reproduces_every_case_byte_for_byte():
    assert verify(DEFAULT_MANIFEST, COMMITTED_CASES) == []
