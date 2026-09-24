"""Which head-side lines did the PR add or change?"""

from analysis.diff import (
    MAX_LINES_FOR_LOCAL_DIFF,
    UNAVAILABLE,
    build_file_diff,
    diff_from_contents,
    parse_patch,
)

PATCH = """@@ -1,4 +1,6 @@
 line one
-line two
+line two changed
+inserted a
 line three
+inserted b
 line four
"""


def test_parse_patch_reports_head_side_added_lines():
    diff = parse_patch(PATCH)
    assert diff.available and diff.source == "github_patch"
    assert diff.added_lines == frozenset({2, 3, 5})


def test_parse_patch_handles_multiple_hunks_and_no_newline_marker():
    patch = (
        "@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
        "@@ -10,2 +10,3 @@\n x\n+new\n y\n\\ No newline at end of file\n"
    )
    diff = parse_patch(patch)
    assert diff.added_lines == frozenset({2, 11})


def test_parse_patch_deletion_only_hunk_adds_no_lines():
    diff = parse_patch("@@ -1,3 +1,2 @@\n a\n-b\n c\n")
    assert diff.added_lines == frozenset()
    assert diff.available


def test_touches_checks_the_whole_flagged_range():
    diff = parse_patch(PATCH)
    assert diff.touches(3, 3)
    assert diff.touches(1, 2)  # range overlaps line 2
    assert not diff.touches(4, 4)


def test_difflib_fallback_matches_the_expected_added_lines():
    base = "one\ntwo\nthree\nfour\n"
    head = "one\ntwo changed\ninserted\nthree\nfour\n"
    diff = diff_from_contents(base, head)
    assert diff.source == "difflib"
    assert diff.added_lines == frozenset({2, 3})


def test_new_file_marks_every_line_as_added():
    diff = diff_from_contents(None, "a\nb\nc")
    assert diff.source == "new_file"
    assert diff.added_lines == frozenset({1, 2, 3})


def test_huge_inputs_are_not_diffed_locally_and_say_so():
    big = "x\n" * (MAX_LINES_FOR_LOCAL_DIFF + 10)
    diff = diff_from_contents(big, big + "y\n")
    assert diff is UNAVAILABLE
    assert diff.available is False


def test_build_file_diff_prefers_github_patch_then_difflib_then_unavailable():
    assert build_file_diff(PATCH, "a", "b").source == "github_patch"
    assert build_file_diff(None, "a\nb\n", "a\nc\n").source == "difflib"
    assert build_file_diff(None, None, "a\n").source == "new_file"
    assert build_file_diff(PATCH, "a", None).available is False
