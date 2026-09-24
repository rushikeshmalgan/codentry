"""Finding identity v2: content-anchored, not line-number-based."""

from analysis.finding import Finding
from analysis.identity import (
    assign_identities,
    compute_dedup_hash,
    compute_identity_key,
    normalize_anchor,
    normalize_message,
)


def _f(line, rule="no-unused-vars", msg="'x' is assigned a value but never used.", path="a.js",
       source="ESLINT", end=None):
    return Finding(
        source=source,
        category="correctness",
        severity="high",
        title=rule,
        description=msg,
        file_path=path,
        start_line=line,
        end_line=end or line,
    )


def _identify(findings, content, path="a.js", scope="repo-1", path_map=None):
    assign_identities(findings, {path: content}, scope, path_map)
    return findings


BEFORE = "function f() {\n  var x = 1;\n  return 2;\n}\n"
# Two unrelated lines inserted ABOVE the flagged line: it moves from line 2 to line 4.
SHIFTED = "// header\n// another\nfunction f() {\n  var x = 1;\n  return 2;\n}\n"


def test_identity_is_stable_when_unrelated_code_shifts_the_line_number():
    (before,) = _identify([_f(2)], BEFORE)
    (after,) = _identify([_f(4)], SHIFTED)

    assert before.start_line != after.start_line
    assert before.identity_key == after.identity_key
    assert before.dedup_hash == after.dedup_hash


def test_identity_changes_when_the_flagged_line_itself_changes():
    (before,) = _identify([_f(2)], BEFORE)
    (after,) = _identify([_f(2)], "function f() {\n  var x = compute();\n  return 2;\n}\n")
    assert before.identity_key != after.identity_key


def test_identity_ignores_whitespace_only_changes_on_the_flagged_line():
    (before,) = _identify([_f(2)], BEFORE)
    (after,) = _identify([_f(2)], "function f() {\n\t\tvar   x  =  1;\n  return 2;\n}\n")
    assert before.identity_key == after.identity_key


def test_identity_differs_by_rule_source_path_and_scope():
    base = _identify([_f(2)], BEFORE)[0].identity_key
    assert _identify([_f(2, rule="no-undef")], BEFORE)[0].identity_key != base
    assert _identify([_f(2, source="SEMGREP")], BEFORE)[0].identity_key != base
    assert _identify([_f(2, path="b.js")], BEFORE, path="b.js")[0].identity_key != base
    assert _identify([_f(2)], BEFORE, scope="repo-2")[0].identity_key != base


def test_identical_flagged_lines_get_distinct_dedup_hashes_but_one_identity_key():
    content = "var x = 1;\nvar x = 1;\n"
    a, b = _identify([_f(1), _f(2)], content)
    assert a.identity_key == b.identity_key
    assert a.dedup_hash != b.dedup_hash


def test_occurrence_order_is_deterministic_regardless_of_input_order():
    content = "var x = 1;\nvar x = 1;\n"
    f1, f2 = _f(1), _f(2)
    _identify([f2, f1], content)
    g1, g2 = _f(1), _f(2)
    _identify([g1, g2], content)
    assert (f1.dedup_hash, f2.dedup_hash) == (g1.dedup_hash, g2.dedup_hash)


def test_renamed_file_keeps_identity_through_the_path_map():
    head = _identify([_f(2, path="new/name.js")], BEFORE, path="new/name.js")[0]
    base = _identify(
        [_f(2, path="old/name.js")],
        BEFORE,
        path="old/name.js",
        path_map={"old/name.js": "new/name.js"},
    )[0]
    assert head.identity_key == base.identity_key


def test_message_normalization_strips_line_references_and_whitespace_and_case():
    assert normalize_message("Unexpected  token at line 12") == normalize_message(
        "unexpected token AT line 40"
    )
    assert normalize_message("  A   B ") == "a b"


def test_anchor_is_the_flagged_source_text_not_its_position():
    assert normalize_anchor(BEFORE, 2, 2) == "var x = 1;"
    assert normalize_anchor(BEFORE, 2, 3) == "var x = 1; return 2;"
    assert normalize_anchor(BEFORE, 99, 99) == ""
    assert normalize_anchor(None, 1, 1) == ""


def test_hash_functions_are_deterministic_sha256_hex():
    key = compute_identity_key("s", "ESLINT", "a.js", "r", "m", "anchor")
    assert key == compute_identity_key("s", "ESLINT", "a.js", "r", "m", "anchor")
    assert len(key) == 64
    assert compute_dedup_hash(key, 0) != compute_dedup_hash(key, 1)
