"""Identity-stability experiment: the transformations, the comparison, and one small
end-to-end run with the real tools."""

import json

import pytest

from analysis.workspace import SourceFile
from evaluation import identity_stability as ids

SOURCE = "const a = 1;\n\nfunction f(x) {\n  return eval(x);\n}\n"


# ---- transformations (pure) ---------------------------------------------------
def test_line_shift_moves_every_line_down_without_changing_any_line():
    shifted = ids.line_shift(SOURCE, 3)
    assert shifted.split("\n")[3:] == SOURCE.split("\n")
    assert shifted.startswith("\n\n\n")


def test_trailing_whitespace_keeps_the_line_count_and_blank_lines_untouched():
    changed = ids.trailing_whitespace(SOURCE)
    old, new = SOURCE.split("\n"), changed.split("\n")
    assert len(old) == len(new)
    for a, b in zip(old, new, strict=True):
        assert b == (a + "  " if a.strip() else a)
    assert [line.rstrip() for line in new] == old


def test_the_transformations_never_change_the_token_content():
    for transform in ids.TRANSFORMS.values():
        assert transform(SOURCE).split() == SOURCE.split()


# ---- comparing key multisets -----------------------------------------------------
def test_identical_multisets_are_fully_stable():
    row = ids.compare_keys(["a", "b", "b"], ["b", "a", "b"])
    assert row == {"before": 3, "after": 3, "stable": 3, "vanished": 0, "appeared": 0}


def test_repeated_keys_are_counted_by_multiplicity_not_by_presence():
    row = ids.compare_keys(["k", "k", "k"], ["k"])
    assert row["stable"] == 1 and row["vanished"] == 2 and row["appeared"] == 0


def test_changed_and_new_keys_are_reported_not_hidden():
    row = ids.compare_keys(["a", "b"], ["a", "c", "d"])
    assert (row["stable"], row["vanished"], row["appeared"]) == (1, 1, 2)


def test_an_identity_that_depended_on_line_numbers_would_be_caught():
    """The experiment must be able to fail: keys that embed the line number do not
    survive a line shift, and compare_keys says so."""
    before = [f"rule|{n}" for n in (4, 9)]
    after = [f"rule|{n + 3}" for n in (4, 9)]
    row = ids.compare_keys(before, after)
    assert row["stable"] == 0 and row["vanished"] == 2 and row["appeared"] == 2


# ---- end to end with the real tools (small) -------------------------------------
@pytest.fixture(scope="module")
def experiment():
    files = [
        SourceFile("a/x.js", SOURCE),
        SourceFile("a/clean.js", "function add(a, b) {\n  return a + b;\n}\n\nmodule.exports = { add };\n"),
        SourceFile("b/y.ts", "export const loose: any = 1;\n"),
    ]
    return ids.run_experiment(files)


def test_only_files_that_have_findings_are_used(experiment):
    assert experiment["files_examined"] == 3
    assert experiment["files_used"] == ["a/x.js", "b/y.ts"]
    assert experiment["findings_before"] >= 2  # eval (Semgrep) + no-explicit-any (ESLint)


def test_real_findings_keep_their_identity_under_both_transformations(experiment):
    for name in ("line_shift", "trailing_whitespace"):
        row = experiment["transforms"][name]
        assert row["before"] == experiment["findings_before"]
        assert row["stable"] == row["before"] and row["vanished"] == 0 and row["appeared"] == 0, name
        assert row["stable_fraction"] == 1.0


def test_the_record_names_its_tool_versions_and_is_json_serializable(experiment):
    assert experiment["schema"] == ids.SCHEMA
    assert experiment["tools"]["semgrep_version"] and experiment["tools"]["eslint_version"]
    assert json.loads(json.dumps(experiment)) == experiment
