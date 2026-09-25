"""Seeded selection, parse validity, range integrity and determinism of the
mutation generator, on a synthetic source (no vendored data, no network)."""

import difflib
import random

import pytest

from evaluation.generators.mutate import (
    INJECTION_NAMES,
    INJECTIONS,
    LOGIC_OPERATORS,
    STRATUM_LOGIC,
    STRATUM_RULE_ALIGNED,
    GeneratorError,
    Mutant,
    _accept,
    _draw_order,
    _require_simple_text,
    derive_seed,
    diff_head_range,
    generate_logic,
    generate_rule_aligned,
    run_helper,
)

BASE = (
    "async function load(items, opts) {\n"
    "  if (!items) return [];\n"
    "  if (opts == null) return null;\n"
    "  let total = 0;\n"
    "  for (let i = 0; i < items.length; i++) {\n"
    "    const v = await fetchOne(items[i]);\n"
    "    if (v > 10 && v !== 42) {\n"
    "      total += v * 2;\n"
    "    }\n"
    "  }\n"
    "  return total >= 100 ? total : 0;\n"
    "}\n"
)


def changed_head_lines(base: str, head: str) -> list[int]:
    matcher = difflib.SequenceMatcher(a=base.split("\n"), b=head.split("\n"), autojunk=False)
    out: list[int] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            out.extend(range(j1 + 1, j2 + 1))
    return out


@pytest.fixture(scope="module")
def logic():
    return generate_logic(BASE, "load.js", seed=1, count=12)


@pytest.fixture(scope="module")
def injected():
    return generate_rule_aligned(BASE, "load.js", seed=1, count=5)


# ---- determinism -----------------------------------------------------------
def test_the_same_seed_gives_the_same_mutants():
    again = generate_logic(BASE, "load.js", seed=1, count=12)
    first = generate_logic(BASE, "load.js", seed=1, count=12)
    assert [(m.operator, m.head_text) for m in first.mutants] == [
        (m.operator, m.head_text) for m in again.mutants
    ]
    assert first.discarded == again.discarded


def test_a_different_seed_gives_different_mutants(logic):
    other = generate_logic(BASE, "load.js", seed=2, count=12)
    assert [m.head_text for m in other.mutants] != [m.head_text for m in logic.mutants]


def test_rule_aligned_generation_is_deterministic_too(injected):
    again = generate_rule_aligned(BASE, "load.js", seed=1, count=5)
    assert [m.head_text for m in again.mutants] == [m.head_text for m in injected.mutants]


def test_derived_seeds_are_stable_and_separate_files_and_strata():
    # A regression pin, not an independent oracle: if this changes, every committed case
    # would regenerate differently (see test_generated_cases.py).
    assert derive_seed(20260925, "validator/src/lib/isDate.js", STRATUM_LOGIC) == 8363297600688285175
    seeds = {
        derive_seed(1, "a", STRATUM_LOGIC),
        derive_seed(2, "a", STRATUM_LOGIC),
        derive_seed(1, "b", STRATUM_LOGIC),
        derive_seed(1, "a", STRATUM_RULE_ALIGNED),
    }
    assert len(seeds) == 4
    assert all(0 <= s < 2**63 for s in seeds)


def test_operators_are_drawn_evenly_not_in_proportion_to_how_common_their_syntax_is():
    """A file with 30 constants and one comparison must not almost never mutate the
    comparison: choose the operator first, then a site within it."""
    by_operator = {"rare": [{"id": "r"}], "common": [{"id": i} for i in range(30)]}
    first_is_rare = sum(
        _draw_order(by_operator, random.Random(seed))[0]["id"] == "r" for seed in range(200)
    )
    assert 70 <= first_is_rare <= 130, first_is_rare  # ~100 expected (1/31 would be ~6)


# ---- one edit, exact range, valid syntax ------------------------------------
def test_requested_count_is_met_and_indices_are_sequential(logic):
    assert len(logic.mutants) == 12
    assert [m.index for m in logic.mutants] == list(range(1, 13))
    assert {m.stratum for m in logic.mutants} == {STRATUM_LOGIC}


def test_every_mutant_is_a_different_program_and_all_are_distinct(logic):
    heads = [m.head_text for m in logic.mutants]
    assert BASE not in heads
    assert len(set(heads)) == len(heads)


def test_ground_truth_range_equals_the_independent_diff_range(logic, injected):
    for m in [*logic.mutants, *injected.mutants]:
        assert diff_head_range(BASE, m.head_text) == (m.start_line, m.end_line), m.operator


def test_each_mutant_applies_to_exactly_one_location(logic):
    for m in logic.mutants:
        if m.operator == "drop-guard":
            assert len(BASE.split("\n")) - len(m.head_text.split("\n")) >= 1  # only deleted lines
            assert changed_head_lines(BASE, m.head_text) == []  # nothing remains that differs
        else:
            assert changed_head_lines(BASE, m.head_text) == [m.start_line], m.operator
            assert m.start_line == m.end_line


def test_every_mutant_parses(logic, injected):
    texts = [m.head_text for m in [*logic.mutants, *injected.mutants]]
    results = run_helper(
        "check", [{"name": str(i), "filename": "load.js", "text": t} for i, t in enumerate(texts)]
    )["results"]
    assert all(r["ok"] for r in results), [r["errors"] for r in results if not r["ok"]]


def test_the_parse_check_really_rejects_broken_code():
    (bad, good) = run_helper(
        "check",
        [
            {"name": "bad", "filename": "x.js", "text": "function ( {"},
            {"name": "good", "filename": "x.js", "text": "function f() {}"},
        ],
    )["results"]
    assert bad["ok"] is False and bad["errors"]
    assert good["ok"] is True


def test_unparseable_and_duplicate_candidates_are_discarded_and_counted():
    ok_head = "const a = 2;\n"
    candidates = [
        ({"operator": "constant-change", "detail": "d"}, "function ( {\n", (1, 1)),
        ({"operator": "constant-change", "detail": "d"}, ok_head, (1, 1)),
        ({"operator": "constant-change", "detail": "d"}, ok_head, (1, 1)),  # same program again
        ({"operator": "constant-change", "detail": "d"}, "const a = 3;\nconst b = 9;\n", (1, 1)),
    ]
    result = _accept(
        "const a = 1;\n", "x.js", candidates, 10, STRATUM_LOGIC,
        operator_of=lambda s: s["operator"], detail_of=lambda s: s["detail"],
    )
    assert [m.head_text for m in result.mutants] == [ok_head]
    assert result.discarded == {"parse_error": 1, "range_mismatch": 1, "duplicate": 1}


def test_all_eight_operators_are_reachable_from_the_generator():
    every = generate_logic(BASE, "load.js", seed=7, count=200)
    assert {m.operator for m in every.mutants} == set(LOGIC_OPERATORS)


# ---- rule-aligned injections -------------------------------------------------
def test_an_injection_is_exactly_one_inserted_line_of_a_known_pattern(injected):
    assert len(injected.mutants) == 5
    rendered = {t.replace("{P}", p) for t in INJECTIONS.values() for p in ("items", "opts")}
    for m in injected.mutants:
        base_lines, head_lines = BASE.split("\n"), m.head_text.split("\n")
        assert len(head_lines) == len(base_lines) + 1
        inserted = head_lines[m.start_line - 1]
        assert m.start_line == m.end_line
        assert head_lines[: m.start_line - 1] + head_lines[m.start_line :] == base_lines
        assert inserted.strip() in rendered, inserted
        assert inserted.startswith("  ")  # takes the indentation of the statement it precedes
        assert m.operator in INJECTION_NAMES


def test_all_four_injection_patterns_are_used_and_they_are_never_mixed_into_the_logic_stratum(injected):
    assert {m.operator for m in injected.mutants} == set(INJECTION_NAMES)
    assert {m.stratum for m in injected.mutants} == {STRATUM_RULE_ALIGNED}
    assert not set(INJECTION_NAMES) & set(LOGIC_OPERATORS)


def test_a_source_with_no_function_bodies_yields_no_injections():
    result = generate_rule_aligned("const a = 1;\nconst b = 2;\n", "flat.js", seed=1, count=3)
    assert result.mutants == []


# ---- input hygiene -----------------------------------------------------------
def test_sources_with_carriage_returns_or_non_bmp_characters_are_refused():
    with pytest.raises(GeneratorError, match="CR"):
        _require_simple_text("a\r\nb\r\n", "crlf.js")
    with pytest.raises(GeneratorError, match="non-BMP"):
        _require_simple_text("const s = '\U0001F600';\n", "emoji.js")
    _require_simple_text("const s = 'café';\n", "ok.js")  # BMP non-ASCII is fine


def test_mutants_are_frozen_records():
    m = Mutant(STRATUM_LOGIC, "constant-change", 1, "x", 1, 1, "d")
    with pytest.raises(AttributeError):
        m.operator = "other"
