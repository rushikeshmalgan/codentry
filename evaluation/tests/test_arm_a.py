"""Arm A end to end, with the real ESLint and Semgrep (no mocks): a golden test on
the existing analysis fixtures, plus the differential classifications.

These run the actual tools, so they need Node + the ESLint baseline install and
Semgrep, exactly like services/ai-review/tests. Each scenario is analyzed once
per module and shared between assertions.
"""


import pytest

from evaluation.case import CaseFile, CaseInputs
from evaluation.runners.arm_a_static import (
    ARM_ID,
    REPORTED_POLICY,
    arm_label,
    build_snapshot,
    run_arm_a,
)
from evaluation.tests.helpers import REPO_ROOT

FIXTURES = REPO_ROOT / "services" / "ai-review" / "analysis" / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def inputs_for(case_id: str, files: list[CaseFile]) -> CaseInputs:
    return CaseInputs(
        id=case_id, language="javascript", base_sha="n/a", head_sha="n/a", files=tuple(files)
    )


def summary(findings):
    return [(f.change_status, f.source, f.title, f.file_path, f.start_line) for f in findings]


# ---- no tools needed --------------------------------------------------------
def test_build_snapshot_maps_case_files_to_a_pull_request_snapshot():
    snapshot = build_snapshot(
        inputs_for(
            "c1",
            [
                CaseFile("lib/new.js", "renamed", "lib/old.js", "a\n", "b\n"),
                CaseFile("x.js", "added", None, None, "c\n"),
                CaseFile("y.js", "removed", None, "d\n", None),
            ],
        )
    )
    renamed, added, removed = snapshot.files
    assert renamed.path == "lib/new.js" and renamed.previous_path == "lib/old.js"
    assert renamed.base.path == "lib/old.js"  # base content is filed under its OLD path
    assert renamed.head.path == "lib/new.js"
    assert added.base is None and added.head.content == "c\n"
    assert removed.head is None and removed.base.content == "d\n"
    assert snapshot.rename_map == {"lib/old.js": "lib/new.js"}
    assert snapshot.trusted_config_text is None  # the arm never reads a config from the case
    assert all(f.patch is None for f in snapshot.files)  # offline: no GitHub patch


def test_the_arm_is_only_handed_case_inputs_never_ground_truth():
    assert "ground_truth" not in CaseInputs.__dataclass_fields__


def test_arm_label_names_the_ruleset_not_semgrep_alone():
    label = arm_label("1.2.3")
    assert "Codentry baseline ruleset (6 rules)" in label and "Semgrep 1.2.3" in label
    assert ARM_ID == "A" and REPORTED_POLICY == "change_status == 'new'"


# ---- real tools ------------------------------------------------------------
@pytest.fixture(scope="module")
def added_fixtures():
    """Every analysis fixture added by the change: nothing existed before, so all
    findings must be classified `new`."""
    names = ("eslint_sample.js", "semgrep_sample.js", "clean_sample.js")
    files = [CaseFile(n, "added", None, None, fixture_text(n)) for n in names]
    return run_arm_a(inputs_for("golden-added", files))


def test_golden_findings_on_the_analysis_fixtures(added_fixtures):
    assert added_fixtures.status == "completed"
    assert added_fixtures.error_code is None
    assert summary(added_fixtures.findings) == [
        ("new", "ESLINT", "no-unused-vars", "eslint_sample.js", 2),
        ("new", "ESLINT", "no-undef", "eslint_sample.js", 3),
        ("new", "SEMGREP", "hardcoded-secret", "semgrep_sample.js", 1),
        ("new", "SEMGREP", "eval-usage", "semgrep_sample.js", 4),
        ("new", "SEMGREP", "sql-string-concatenation", "semgrep_sample.js", 8),
    ]
    assert not any(f.file_path == "clean_sample.js" for f in added_fixtures.findings)


def test_reported_findings_are_exactly_the_new_ones(added_fixtures):
    assert added_fixtures.reported == added_fixtures.findings
    assert all(f.change_status == "new" and f.in_diff for f in added_fixtures.findings)


def test_findings_carry_a_line_independent_identity(added_fixtures):
    keys = [f.identity_key for f in added_fixtures.findings]
    assert all(keys) and len(set(keys)) == len(keys)
    assert all(f.source == "ESLINT" or f.source == "SEMGREP" for f in added_fixtures.findings)
    assert all(f.source != "AI" for f in added_fixtures.findings)


def test_analysis_meta_records_what_is_needed_to_reproduce(added_fixtures):
    head = added_fixtures.analysis_meta["head"]
    for key in ("eslint_version", "semgrep_version", "ruleset_sha256", "baseline_config_sha256"):
        assert head[key], key
    assert len(head["ruleset_sha256"]) == 64 and len(head["baseline_config_sha256"]) == 64
    assert head["config_source"] == "baseline"  # never a PR- or case-supplied config
    assert added_fixtures.analysis_meta["differential"]["diff_sources"] == {"new_file": 3}


@pytest.fixture(scope="module")
def unchanged_and_removed():
    """semgrep_sample.js unchanged, eslint_sample.js deleted, clean_sample.js added."""
    semgrep = fixture_text("semgrep_sample.js")
    files = [
        CaseFile("semgrep_sample.js", "modified", None, semgrep, semgrep),
        CaseFile("eslint_sample.js", "removed", None, fixture_text("eslint_sample.js"), None),
        CaseFile("clean_sample.js", "added", None, None, fixture_text("clean_sample.js")),
    ]
    return run_arm_a(inputs_for("golden-existing-fixed", files))


def test_unchanged_findings_are_existing_and_removed_ones_are_fixed(unchanged_and_removed):
    assert unchanged_and_removed.status == "completed"
    by_status = {}
    for f in unchanged_and_removed.findings:
        by_status.setdefault(f.change_status, []).append((f.source, f.title, f.file_path, f.start_line))
    assert sorted(by_status["existing"]) == [
        ("SEMGREP", "eval-usage", "semgrep_sample.js", 4),
        ("SEMGREP", "hardcoded-secret", "semgrep_sample.js", 1),
        ("SEMGREP", "sql-string-concatenation", "semgrep_sample.js", 8),
    ]
    assert sorted(by_status["fixed"]) == [
        ("ESLINT", "no-undef", "eslint_sample.js", 3),
        ("ESLINT", "no-unused-vars", "eslint_sample.js", 2),
    ]
    assert "new" not in by_status


def test_pre_existing_and_fixed_findings_are_never_reported(unchanged_and_removed):
    assert unchanged_and_removed.reported == []
    meta = unchanged_and_removed.analysis_meta["differential"]
    assert (meta["new"], meta["existing"], meta["fixed"]) == (0, 3, 2)
