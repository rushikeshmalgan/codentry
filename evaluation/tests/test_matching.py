"""Matching findings to ground truth: overlap, ±k tolerance, file identity, renames."""

import pytest

from evaluation.metrics.matching import (
    DEFAULT_TOLERANCE,
    TOLERANCES,
    Span,
    duplicate_count,
    hits,
    match,
    ratio,
)

DEFECT = Span("src/a.js", 10, 12)


def f(file="src/a.js", start=10, end=10):
    return Span(file, start, end)


def test_defaults_are_the_documented_ones():
    assert DEFAULT_TOLERANCE == 2
    assert TOLERANCES == (0, 2, 5)


@pytest.mark.parametrize(
    "finding, expected",
    [
        (f(start=10, end=10), True),  # inside, first line
        (f(start=11, end=11), True),  # inside
        (f(start=12, end=12), True),  # inside, last line
        (f(start=8, end=10), True),  # straddles the start
        (f(start=12, end=20), True),  # straddles the end
        (f(start=1, end=100), True),  # contains the defect
        (f(start=9, end=9), False),  # one line before, k=0
        (f(start=13, end=13), False),  # one line after, k=0
    ],
)
def test_overlap_at_zero_tolerance(finding, expected):
    assert hits(finding, DEFECT, tolerance=0) is expected


@pytest.mark.parametrize(
    "line, k, expected",
    [
        (8, 2, True),  # exactly k above the range
        (7, 2, False),  # k + 1 above
        (14, 2, True),  # exactly k below
        (15, 2, False),  # k + 1 below
        (5, 5, True),
        (4, 5, False),
        (17, 5, True),
        (18, 5, False),
        (9, 1, True),
        (8, 1, False),
    ],
)
def test_tolerance_widens_the_defect_range_by_k_lines_each_side(line, k, expected):
    assert hits(f(start=line, end=line), DEFECT, tolerance=k) is expected


def test_a_finding_in_a_different_file_never_matches():
    assert hits(f(file="src/b.js"), DEFECT, tolerance=5) is False


def test_a_renamed_file_matches_only_under_its_head_path():
    """Identity path = the path at the head. Ground truth is written against head
    paths, so a finding reported under the pre-rename path must not match."""
    defect = Span("lib/reporting.js", 13, 13)
    assert hits(Span("lib/reporting.js", 13, 13), defect, 0) is True
    assert hits(Span("lib/report.js", 13, 13), defect, 5) is False


def test_negative_tolerance_is_an_error():
    with pytest.raises(ValueError):
        hits(f(), DEFECT, tolerance=-1)


def test_more_tolerance_never_removes_a_hit():
    """Sensitivity must be monotone: k=0 hits ⊆ k=2 hits ⊆ k=5 hits."""
    for line in range(1, 25):
        finding = f(start=line, end=line)
        results = [hits(finding, DEFECT, k) for k in TOLERANCES]
        assert results == sorted(results), (line, results)


# ---- match(): recall / precision / location accounting ---------------------
def test_match_counts_detected_missed_true_and_false_positives():
    defects = [Span("a.js", 5, 5), Span("a.js", 50, 52), Span("b.js", 1, 1)]
    reported = [
        Span("a.js", 5, 5),  # exact hit on defect 0
        Span("a.js", 7, 7),  # 2 lines away: hit only with k>=2
        Span("a.js", 200, 200),  # nowhere near anything
    ]
    m0 = match(reported, defects, 0)
    assert m0.detected_defects == (0,)
    assert m0.missed_defects == (1, 2)
    assert m0.matched_findings == (0,)
    assert m0.unmatched_findings == (1, 2)

    m2 = match(reported, defects, 2)
    assert m2.detected_defects == (0,)  # finding 1 also lands on defect 0
    assert m2.matched_findings == (0, 1)
    assert m2.unmatched_findings == (2,)
    assert m2.exactly_located_findings == (0,)  # only finding 0 points at the defective lines


def test_location_accuracy_inputs_distinguish_near_from_exact():
    defects = [Span("a.js", 10, 10)]
    reported = [Span("a.js", 12, 12)]
    assert match(reported, defects, 0).matched_findings == ()
    near = match(reported, defects, 2)
    assert near.matched_findings == (0,)
    assert near.exactly_located_findings == ()


def test_several_findings_on_one_defect_are_all_true_positives_but_detect_it_once():
    defects = [Span("a.js", 10, 10)]
    reported = [Span("a.js", 10, 10), Span("a.js", 10, 10), Span("a.js", 11, 11)]
    m = match(reported, defects, 2)
    assert m.detected_defects == (0,)
    assert m.matched_findings == (0, 1, 2)
    assert m.unmatched_findings == ()


def test_a_clean_change_makes_every_finding_a_false_positive():
    m = match([Span("a.js", 1, 1), Span("a.js", 9, 9)], [], 2)
    assert m.defects == 0
    assert m.unmatched_findings == (0, 1)
    assert m.detected_defects == () and m.missed_defects == ()


def test_no_findings_means_every_defect_is_missed():
    m = match([], [Span("a.js", 1, 1)], 2)
    assert m.missed_defects == (0,)
    assert m.reported == 0


def test_match_is_independent_of_the_order_of_inputs():
    defects = [Span("a.js", 5, 5), Span("b.js", 9, 9)]
    reported = [Span("b.js", 9, 9), Span("a.js", 40, 40), Span("a.js", 5, 6)]
    forward = match(reported, defects, 2)
    backward = match(list(reversed(reported)), list(reversed(defects)), 2)
    assert len(forward.detected_defects) == len(backward.detected_defects) == 2
    assert len(forward.unmatched_findings) == len(backward.unmatched_findings) == 1


# ---- duplicates and ratios --------------------------------------------------
def test_duplicate_count_counts_repeats_beyond_the_first():
    assert duplicate_count([]) == 0
    assert duplicate_count(["a", "b", "c"]) == 0
    assert duplicate_count(["a", "a", "b", "a"]) == 2


def test_ratio_returns_none_for_an_empty_denominator_never_zero_or_one():
    assert ratio(0, 0) is None
    assert ratio(3, 0) is None
    assert ratio(0, 4) == 0.0
    assert ratio(1, 4) == 0.25
