"""Differential classification: base -> head -> new / existing / fixed."""

from analysis.diff import FileDiff, parse_patch
from analysis.differential import classify
from analysis.finding import Finding
from analysis.identity import assign_identities


def _f(line, rule="no-unused-vars", msg="'x' is assigned a value but never used.", path="a.js"):
    return Finding(
        source="ESLINT",
        category="correctness",
        severity="high",
        title=rule,
        description=msg,
        file_path=path,
        start_line=line,
        end_line=line,
    )


def _run(base_content, base_findings, head_content, head_findings, patch=None, path="a.js",
         base_path=None, path_map=None):
    base_path = base_path or path
    assign_identities(base_findings, {base_path: base_content}, "repo", path_map)
    assign_identities(head_findings, {path: head_content}, "repo")
    diff = parse_patch(patch) if patch else FileDiff(added_lines=frozenset(), available=True)
    return classify(head_findings, base_findings, {path: diff})


def _by_status(result):
    out = {"new": [], "existing": [], "fixed": []}
    for f in result.findings:
        out[f.change_status].append(f)
    return out


def test_pre_existing_finding_is_existing_not_new_even_when_lines_shift():
    base = "function f() {\n  var x = 1;\n}\n"
    head = "// added header\n// another\nfunction f() {\n  var x = 1;\n}\n"
    patch = "@@ -0,0 +1,2 @@\n+// added header\n+// another\n"

    result = _run(base, [_f(2)], head, [_f(4)], patch)
    groups = _by_status(result)

    assert len(groups["new"]) == 0
    assert len(groups["existing"]) == 1
    existing = groups["existing"][0]
    assert existing.start_line == 4 and existing.base_start_line == 2
    assert existing.in_diff is False and existing.moved is False  # drifted, not moved
    assert (result.new_count, result.existing_count, result.fixed_count) == (0, 1, 0)


def test_finding_introduced_by_the_pr_is_new_and_in_diff():
    base = "function f() {\n  return 1;\n}\n"
    head = "function f() {\n  var x = 1;\n  return 1;\n}\n"
    patch = "@@ -1,3 +1,4 @@\n function f() {\n+  var x = 1;\n   return 1;\n }\n"

    result = _run(base, [], head, [_f(2)], patch)
    (new,) = _by_status(result)["new"]

    assert new.in_diff is True
    assert new.base_start_line is None


def test_finding_removed_by_the_pr_is_fixed():
    base = "function f() {\n  var x = 1;\n  return 1;\n}\n"
    head = "function f() {\n  return 1;\n}\n"

    result = _run(base, [_f(2)], head, [], "@@ -1,4 +1,3 @@\n function f() {\n-  var x = 1;\n   return 1;\n }\n")
    groups = _by_status(result)

    assert len(groups["fixed"]) == 1 and groups["fixed"][0].start_line == 2
    assert result.fixed_count == 1 and result.new_count == 0


def test_existing_finding_on_a_line_the_pr_re_added_is_moved():
    base = "var x = 1;\nfoo();\nbar();\n"
    head = "foo();\nbar();\nvar x = 1;\n"  # the flagged line was cut and pasted to the end
    patch = "@@ -1,3 +1,3 @@\n-var x = 1;\n foo();\n bar();\n+var x = 1;\n"

    result = _run(base, [_f(1)], head, [_f(3)], patch)
    (existing,) = _by_status(result)["existing"]

    assert existing.moved is True and existing.in_diff is True
    assert existing.base_start_line == 1 and existing.start_line == 3
    assert result.moved_count == 1


def test_added_duplicate_of_an_existing_finding_attributes_new_to_the_added_line():
    base = "var x = 1;\nfoo();\n"
    head = "var x = 1;\nfoo();\nvar x = 1;\n"  # identical statement appended
    patch = "@@ -1,2 +1,3 @@\n var x = 1;\n foo();\n+var x = 1;\n"

    result = _run(base, [_f(1)], head, [_f(1), _f(3)], patch)
    groups = _by_status(result)

    assert [f.start_line for f in groups["new"]] == [3]
    assert [f.start_line for f in groups["existing"]] == [1]


def test_duplicate_inserted_ABOVE_is_still_attributed_to_the_added_line():
    base = "var x = 1;\nfoo();\n"
    head = "var x = 1;\nvar x = 1;\nfoo();\n"  # copy inserted at line 2
    patch = "@@ -1,2 +1,3 @@\n var x = 1;\n+var x = 1;\n foo();\n"

    result = _run(base, [_f(1)], head, [_f(1), _f(2)], patch)
    groups = _by_status(result)

    assert [f.start_line for f in groups["new"]] == [2]


def test_renamed_file_findings_match_across_the_rename():
    content = "var x = 1;\n"
    result = _run(
        content,
        [_f(1, path="old.js")],
        content,
        [_f(1, path="new.js")],
        path="new.js",
        base_path="old.js",
        path_map={"old.js": "new.js"},
    )
    groups = _by_status(result)
    assert len(groups["existing"]) == 1 and not groups["new"] and not groups["fixed"]


def test_new_file_findings_are_all_new():
    head = "var x = 1;\n"
    result = _run(
        "",
        [],
        head,
        [_f(1)],
        "@@ -0,0 +1 @@\n+var x = 1;\n",
    )
    assert result.new_count == 1


def test_classification_does_not_mutate_its_inputs():
    head = [_f(1)]
    assign_identities(head, {"a.js": "var x = 1;\n"}, "repo")
    classify(head, [], {"a.js": FileDiff(frozenset({1}))})
    assert head[0].change_status is None
