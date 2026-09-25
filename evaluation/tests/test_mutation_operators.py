"""The eight logic operators and the rule-aligned injections, on small snippets
where the correct site is known exactly.

These run the real Node helper (TypeScript parser) but no analysis tools and no
network. What each test pins down: the operator finds the site, applies exactly
one edit, changes exactly the recorded line range, and leaves look-alikes alone.
"""

import pytest

from evaluation.generators.mutate import diff_head_range, run_helper


def enumerate_(text: str, filename: str = "x.js") -> dict:
    return run_helper("enumerate", [{"name": "f", "filename": filename, "text": text}])["results"][0]


def sites(text: str, operator: str, filename: str = "x.js") -> list[dict]:
    return [s for s in enumerate_(text, filename)["sites"] if s["operator"] == operator]


def apply(text: str, site: dict) -> str:
    return text[: site["start"]] + site["replacement"] + text[site["end"] :]


def changed_lines(base: str, head: str) -> list[int]:
    """1-based numbers of head lines that do not appear unchanged in the base."""
    import difflib

    matcher = difflib.SequenceMatcher(a=base.split("\n"), b=head.split("\n"), autojunk=False)
    out: list[int] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            out.extend(range(j1 + 1, j2 + 1))
    return out


SNIPPETS = {
    "relational-flip": ("function f(a, b) {\n  return a < b;\n}\n", "a < b", "a <= b"),
    "equality-flip": ("function f(a, b) {\n  return a === b;\n}\n", "a === b", "a !== b"),
    "logical-swap": ("function f(a, b) {\n  return a && b;\n}\n", "a && b", "a || b"),
    "negate-condition": ("function f(a) {\n  if (a > 1) {\n    g();\n  }\n}\n", "if (a > 1)", "if (!(a > 1))"),
    "remove-await": (
        "async function f(p) {\n  const v = await p;\n  return v;\n}\n",
        "const v = await p;",
        "const v = p;",
    ),
    "constant-change": ("const limit = 10;\n", "const limit = 10;", "const limit = 11;"),
}


@pytest.mark.parametrize("operator", sorted(SNIPPETS))
def test_each_operator_applies_one_exact_edit_on_the_recorded_line(operator):
    base, before, after = SNIPPETS[operator]
    found = sites(base, operator)
    assert len(found) == 1, found
    head = apply(base, found[0])
    assert head == base.replace(before, after)
    assert changed_lines(base, head) == [found[0]["line"]]
    assert diff_head_range(base, head) == (found[0]["line"], found[0]["line"])


def test_negating_a_negated_condition_removes_the_bang():
    base = "function f(a) {\n  if (!a) {\n    g();\n  }\n}\n"
    found = sites(base, "negate-condition")
    assert [s["replacement"] for s in found] == ["a"]
    assert apply(base, found[0]) == "function f(a) {\n  if (a) {\n    g();\n  }\n}\n"


def test_relational_flips_cover_all_four_operators_both_ways():
    base = "const r = [a < b, a <= b, a > b, a >= b];\n"
    assert sorted((s["before"], s["replacement"]) for s in sites(base, "relational-flip")) == [
        ("<", "<="), ("<=", "<"), (">", ">="), (">=", ">"),
    ]


def test_equality_flips_cover_loose_and_strict_forms():
    base = "const r = [a == b, a != b, a === b, a !== b];\n"
    assert sorted((s["before"], s["replacement"]) for s in sites(base, "equality-flip")) == [
        ("!=", "=="), ("!==", "==="), ("==", "!="), ("===", "!=="),
    ]


def test_off_by_one_finds_both_the_bound_and_the_index():
    base = "for (let i = 0; i < xs.length; i++) {\n  use(xs[i]);\n}\n"
    found = {s["detail"]: s for s in sites(base, "off-by-one")}
    assert set(found) == {"length -> length - 1", "index -> index + 1"}
    assert apply(base, found["length -> length - 1"]).splitlines()[0] == (
        "for (let i = 0; i < xs.length - 1; i++) {"
    )
    assert apply(base, found["index -> index + 1"]).splitlines()[1] == "  use(xs[i + 1]);"
    for s in found.values():
        assert changed_lines(base, apply(base, s)) == [s["line"]]


def test_drop_guard_removes_a_whole_single_line_guard():
    base = "function f(x) {\n  if (x == null) return null;\n  return x.y;\n}\n"
    (site,) = sites(base, "drop-guard")
    head = apply(base, site)
    assert head == "function f(x) {\n  return x.y;\n}\n"
    # nothing is left on the deleted line, so the range points at the code now in its place
    assert diff_head_range(base, head) == (2, 2)


def test_drop_guard_removes_a_multi_line_block_guard_only_when_it_is_just_an_exit():
    base = (
        "function f(x) {\n"
        "  if (!x) {\n"
        "    return;\n"
        "  }\n"
        "  if (x.y) {\n"
        "    log(x);\n"
        "    return;\n"
        "  }\n"
        "  return x;\n"
        "}\n"
    )
    found = sites(base, "drop-guard")
    assert [s["line"] for s in found] == [2]  # the second `if` does more than exit, so it is not a guard
    assert apply(base, found[0]).startswith("function f(x) {\n  if (x.y) {")


def test_a_guard_with_an_else_or_sharing_its_line_is_not_a_drop_guard_site():
    assert sites("function f(x) {\n  if (x) return 1; else return 2;\n}\n", "drop-guard") == []
    assert sites("function f(x) {\n  g(); if (x) return 1;\n  h();\n}\n", "drop-guard") == []


@pytest.mark.parametrize(
    "text, operator",
    [
        ('const s = "a < b && c === d";\n', "relational-flip"),
        ('const s = "a < b && c === d";\n', "logical-swap"),
        ("// if (a < b && c === 1) return;\n", "relational-flip"),
        ("/* await x; a === b */\n", "equality-flip"),
        ("const t = `${a} < ${b}`;\n", "relational-flip"),
    ],
)
def test_operators_ignore_look_alikes_in_strings_and_comments(text, operator):
    assert sites(text, operator) == []


def test_generics_and_type_level_numbers_are_not_mutated_in_typescript():
    base = "type T = 1 | 2;\nconst xs: Array<number> = [];\nfunction g<A>(a: A): A { return a; }\n"
    ops = {s["operator"] for s in enumerate_(base, "x.ts")["sites"]}
    assert "relational-flip" not in ops
    assert "constant-change" not in ops


def test_numeric_object_keys_and_non_integer_literals_are_left_alone():
    base = "const o = { 1: 'a', 2: 'b' };\nconst f = 1.5;\nconst h = 0xff;\nconst e = 1e3;\n"
    assert sites(base, "constant-change") == []


def test_a_condition_spanning_several_lines_is_not_a_negation_site():
    """Multi-line edits would break the exact one-line ground-truth range, so a
    condition-wide negation is refused; a single token inside it is still fine."""
    base = "function f(a, b) {\n  if (\n    a &&\n    b\n  ) {\n    g();\n  }\n}\n"
    assert sites(base, "negate-condition") == []
    (swap,) = sites(base, "logical-swap")
    assert swap["line"] == 3 and swap["replacement"] == "||"
