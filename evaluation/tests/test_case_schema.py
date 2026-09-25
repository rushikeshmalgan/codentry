"""Case format: the JSON Schema, and the cross-checks the loader adds on top."""

import copy
import os

import pytest

from evaluation.case import (
    CaseError,
    CaseInputs,
    _read_text,  # defense-in-depth check, tested directly
    discover_case_dirs,
    line_count,
    load_case,
    manifest_sha256,
    validate_document,
)
from evaluation.tests.helpers import COMMITTED_CASES, document, write_case


def test_the_committed_cases_validate_and_load():
    dirs = discover_case_dirs(COMMITTED_CASES)
    assert len(dirs) >= 2
    for case_dir in dirs:
        case = load_case(case_dir)
        assert case.id == case_dir.name


def test_a_valid_document_has_no_schema_errors():
    assert validate_document(document()) == []


@pytest.mark.parametrize(
    "mutate, expected_fragment",
    [
        (lambda d: d.pop("license"), "license"),
        (lambda d: d.pop("ground_truth"), "ground_truth"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(unexpected="x"), "unexpected"),
        (lambda d: d.update(id="Has Spaces"), "id:"),
        (lambda d: d.update(stratum="Not A Stratum"), "stratum"),
        (lambda d: d.update(language="python"), "language"),
        (lambda d: d.update(source={"kind": "repository", "url": "https://x", "base_sha": "abc", "head_sha": "def"}), "source"),
        (lambda d: d.update(source={"kind": "carrier-pigeon"}), "source"),
        (lambda d: d.update(files=[]), "files"),
        (lambda d: d["ground_truth"][0].update(start_line=0), "start_line"),
        (lambda d: d["ground_truth"][0].update(kind="vibes"), "kind"),
        (lambda d: d["ground_truth"][0].update(provenance="oracle"), "provenance"),
        (lambda d: d["ground_truth"][0].update(verified_by=[]), "verified_by"),
    ],
)
def test_schema_rejects_malformed_documents(mutate, expected_fragment):
    doc = document()
    mutate(doc)
    errors = validate_document(doc)
    assert errors, "expected schema errors"
    assert any(expected_fragment in e for e in errors), errors


@pytest.mark.parametrize("method", ["llm", "model", "claude", "gpt", "ai_review"])
def test_a_model_is_never_an_accepted_way_to_verify_ground_truth(method):
    doc = document()
    doc["ground_truth"][0]["verified_by"] = [{"method": method, "ref": "asked the model"}]
    assert any("verified_by" in e for e in validate_document(doc))


def test_repository_and_generated_sources_validate():
    repo = {"kind": "repository", "url": "https://github.com/o/r", "base_sha": "a" * 40, "head_sha": "b" * 40}
    generated = {"kind": "generated", "generator": "mutate.py/relational-flip", "seed": 7}
    assert validate_document(document(source=repo)) == []
    assert validate_document(document(source=generated)) == []


def test_repository_sources_may_say_how_the_change_was_derived():
    repo = {"kind": "repository", "url": "https://github.com/o/r", "base_sha": "a" * 40,
            "head_sha": "b" * 40, "derivation": "pull_request", "pull_request": 12}
    assert validate_document(document(source=repo)) == []
    reversed_fix = {**repo, "derivation": "reversed_fix", "base_ref": "Bug-1-fix", "head_ref": "Bug-1"}
    reversed_fix.pop("pull_request")
    assert validate_document(document(source=reversed_fix)) == []
    assert validate_document(document(source={**repo, "derivation": "cherry_pick"}))  # unknown value
    assert validate_document(document(source={**repo, "pull_request": 0}))  # PR numbers start at 1


def test_ground_truth_status_is_required_and_constrains_the_defect_list():
    doc = document()
    doc.pop("ground_truth_status")
    assert any("ground_truth_status" in e for e in validate_document(doc))
    assert validate_document(document(ground_truth_status="maybe"))
    # an unlabeled change cannot carry defects: nobody has labeled it
    assert validate_document(document(ground_truth_status="unlabeled"))
    assert validate_document(document(ground_truth_status="unlabeled", ground_truth=[])) == []
    assert validate_document(document(ground_truth_status="labeled", ground_truth=[])) == []


def test_defects_may_share_a_group_and_a_group_must_be_a_slug():
    doc = document()
    doc["ground_truth"][0]["group"] = "bugsjs-express-3"
    assert validate_document(doc) == []
    doc["ground_truth"][0]["group"] = "Not A Slug"
    assert any("group" in e for e in validate_document(doc))


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "a.js", "status": "added", "head": "h/a.js", "base": "b/a.js"},  # added must have no base
        {"path": "a.js", "status": "added"},  # added needs head
        {"path": "a.js", "status": "modified", "head": "h/a.js"},  # modified needs base
        {"path": "a.js", "status": "removed", "base": "b/a.js", "head": "h/a.js"},  # removed has no head
        {"path": "a.js", "status": "renamed", "base": "b/o.js", "head": "h/a.js"},  # renamed needs previous_path
        {"path": "a.js", "status": "modified", "base": "b/a.js", "head": "h/a.js", "previous_path": "o.js"},
        {"path": "../a.js", "status": "added", "head": "h/a.js"},  # traversal
        {"path": "/abs.js", "status": "added", "head": "h/a.js"},
        {"path": "a\\b.js", "status": "added", "head": "h/a.js"},
        {"path": "a.js", "status": "added", "head": "../../etc/passwd"},
    ],
)
def test_file_entries_must_match_their_status(entry):
    assert validate_document(document(files=[entry], ground_truth=[])), entry


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "a.js", "status": "added", "head": "head/a.js"},
        {"path": "a.js", "status": "removed", "base": "base/a.js"},
        {"path": "n.js", "status": "renamed", "previous_path": "o.js", "base": "base/o.js", "head": "head/n.js"},
        {"path": "a.js", "status": "modified", "base": "base/a.js", "head": "head/a.js"},
    ],
)
def test_each_file_status_has_a_valid_shape(entry):
    assert validate_document(document(files=[entry], ground_truth=[])) == []


# ---- loader cross-checks (things a JSON Schema cannot express) --------------
def test_load_case_returns_inputs_without_ground_truth(tmp_path):
    case = load_case(write_case(tmp_path))
    assert isinstance(case.inputs, CaseInputs)
    assert not hasattr(case.inputs, "ground_truth")  # arms are blind by construction
    assert len(case.ground_truth) == 1
    assert case.inputs.files[0].head_content.startswith("function add")


def test_directory_name_must_equal_the_case_id(tmp_path):
    case_dir = write_case(tmp_path, document(id="t-001"), directory="other-name")
    with pytest.raises(CaseError, match="directory name"):
        load_case(case_dir)


def test_ground_truth_must_point_at_a_changed_file(tmp_path):
    doc = document()
    doc["ground_truth"][0]["file"] = "src/other.js"
    with pytest.raises(CaseError, match="not a changed file"):
        load_case(write_case(tmp_path, doc))


def test_ground_truth_range_must_lie_inside_the_head_file(tmp_path):
    doc = document()
    doc["ground_truth"][0].update(start_line=4, end_line=99)
    with pytest.raises(CaseError, match="past the end"):
        load_case(write_case(tmp_path, doc))


def test_ground_truth_range_must_not_be_inverted(tmp_path):
    doc = document()
    doc["ground_truth"][0].update(start_line=3, end_line=2)
    with pytest.raises(CaseError, match="start_line > end_line"):
        load_case(write_case(tmp_path, doc))


def test_a_referenced_file_that_is_missing_is_an_error_not_a_skip(tmp_path):
    with pytest.raises(CaseError, match="does not exist"):
        load_case(write_case(tmp_path, base=None))


def test_undecodable_content_is_an_error(tmp_path):
    case_dir = write_case(tmp_path)
    (case_dir / "head" / "src" / "add.js").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(CaseError, match="UTF-8"):
        load_case(case_dir)


def test_content_paths_cannot_escape_the_case_directory(tmp_path):
    # ".." is already rejected by the schema ...
    doc = document(files=[{"path": "a.js", "status": "added", "head": "head/../../secret.js"}], ground_truth=[])
    assert validate_document(doc)
    # ... and the loader's own containment check must hold even if that regresses.
    (tmp_path / "secret.js").write_text("x", encoding="utf-8")
    case_dir = tmp_path / "t-001"
    case_dir.mkdir()
    with pytest.raises(CaseError, match="escapes"):
        _read_text(case_dir, "../secret.js", "test")


def test_symlinked_content_is_rejected(tmp_path):
    case_dir = write_case(tmp_path)
    target = tmp_path / "outside.js"
    target.write_text("x", encoding="utf-8")
    link = case_dir / "head" / "src" / "add.js"
    link.unlink()
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    with pytest.raises(CaseError, match="symlink"):
        load_case(case_dir)


def test_duplicate_head_paths_are_rejected(tmp_path):
    entry = {"path": "src/add.js", "status": "modified", "base": "base/src/add.js", "head": "head/src/add.js"}
    doc = document(files=[entry, copy.deepcopy(entry)])
    with pytest.raises(CaseError, match="duplicate"):
        load_case(write_case(tmp_path, doc))


def test_an_empty_ground_truth_is_a_valid_clean_change(tmp_path):
    case = load_case(write_case(tmp_path, document(ground_truth=[])))
    assert case.ground_truth == ()


@pytest.mark.parametrize(
    "text, expected",
    [("", 0), ("a", 1), ("a\n", 1), ("a\nb", 2), ("a\nb\n", 2), ("\n", 1), ("\n\n", 2)],
)
def test_line_count_matches_how_editors_and_git_count(text, expected):
    assert line_count(text) == expected


# ---- manifest hash ---------------------------------------------------------
def test_manifest_hash_is_stable_and_order_independent(tmp_path):
    a = write_case(tmp_path, document(id="a-1"))
    b = write_case(tmp_path, document(id="b-1"))
    assert manifest_sha256([a, b]) == manifest_sha256([b, a])
    assert len(manifest_sha256([a, b])) == 64


def test_manifest_hash_changes_when_any_case_byte_changes(tmp_path):
    a = write_case(tmp_path, document(id="a-1"))
    before = manifest_sha256([a])
    target = a / "head" / "src" / "add.js"
    target.write_bytes(target.read_bytes() + b"// edit\n")
    assert manifest_sha256([a]) != before


def test_manifest_hash_distinguishes_line_endings(tmp_path):
    """Bytes, not decoded text: which is why evaluation/cases/.gitattributes pins `-text`."""
    a = write_case(tmp_path, document(id="a-1"), head="x\ny\n")
    lf = manifest_sha256([a])
    (a / "head" / "src" / "add.js").write_bytes(b"x\r\ny\r\n")
    assert manifest_sha256([a]) != lf


def test_committed_case_files_are_pinned_against_line_ending_conversion():
    attributes = (COMMITTED_CASES / ".gitattributes").read_text(encoding="utf-8")
    assert "-text" in attributes
