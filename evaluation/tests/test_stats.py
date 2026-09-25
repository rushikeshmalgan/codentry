"""Wilson intervals, exact McNemar, seeded bootstrap.

Expected values are from an independent closed form / exact-fraction
computation (see the Day 1 verification), and the two Wilson pairs are the ones
quoted in docs/8_DAY_IMPLEMENTATION_PLAN.md.
"""

import math
from fractions import Fraction

import pytest

from evaluation.metrics.stats import bootstrap_interval, mcnemar_exact, wilson_interval


def mean(xs):
    return sum(xs) / len(xs)


# ---- Wilson -----------------------------------------------------------------
@pytest.mark.parametrize(
    "successes, n, low, high",
    [
        (6, 20, 0.145, 0.519),  # plan: 6/20 -> 0.145-0.519
        (36, 120, 0.225, 0.387),  # plan: 36/120 -> 0.225-0.387
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
        (1, 3, 0.0615, 0.7923),
    ],
)
def test_wilson_matches_known_values(successes, n, low, high):
    got_low, got_high = wilson_interval(successes, n)
    assert got_low == pytest.approx(low, abs=1e-3)
    assert got_high == pytest.approx(high, abs=1e-3)


def test_wilson_more_data_gives_a_narrower_interval():
    small = wilson_interval(6, 20)
    large = wilson_interval(36, 120)  # same proportion, 6x the data
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_wilson_interval_contains_the_point_estimate_and_stays_in_unit_range():
    for n in (1, 2, 5, 17, 100):
        for successes in range(n + 1):
            low, high = wilson_interval(successes, n)
            assert 0.0 <= low <= successes / n <= high <= 1.0


def test_wilson_with_no_observations_is_the_vacuous_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_a_higher_confidence_level_widens_the_interval():
    narrow = wilson_interval(6, 20, confidence=0.90)
    wide = wilson_interval(6, 20, confidence=0.99)
    assert wide[0] < narrow[0] and wide[1] > narrow[1]


@pytest.mark.parametrize("args", [(-1, 5), (6, 5), (1, -2)])
def test_wilson_rejects_impossible_counts(args):
    with pytest.raises(ValueError):
        wilson_interval(*args)


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.5, 1.5])
def test_wilson_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError):
        wilson_interval(1, 2, confidence=confidence)


# ---- McNemar ----------------------------------------------------------------
@pytest.mark.parametrize(
    "only_a, only_b, expected",
    [
        (0, 5, 0.0625),
        (1, 5, 0.21875),
        (3, 3, 1.0),
        (2, 9, 0.0654296875),
        (10, 2, 0.03857421875),
        (0, 0, 1.0),
    ],
)
def test_mcnemar_exact_matches_exact_binomial_arithmetic(only_a, only_b, expected):
    assert mcnemar_exact(only_a, only_b) == pytest.approx(expected, abs=1e-12)


def test_mcnemar_is_symmetric_and_a_valid_probability():
    for a in range(0, 12):
        for b in range(0, 12):
            p = mcnemar_exact(a, b)
            assert p == mcnemar_exact(b, a)
            assert 0.0 <= p <= 1.0


def test_mcnemar_agrees_with_fraction_arithmetic_for_large_counts():
    a, b = 40, 70
    n = a + b
    tail = sum(Fraction(math.comb(n, i), 2**n) for i in range(min(a, b) + 1))
    assert mcnemar_exact(a, b) == pytest.approx(float(min(Fraction(1), 2 * tail)), rel=1e-12)


def test_mcnemar_rejects_negative_counts():
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 3)


# ---- bootstrap ---------------------------------------------------------------
VALUES = [1.0, 2.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0]


def test_bootstrap_is_deterministic_for_a_seed():
    a = bootstrap_interval(VALUES, mean, seed=42, resamples=500)
    b = bootstrap_interval(VALUES, mean, seed=42, resamples=500)
    assert a == b


def test_bootstrap_depends_on_the_seed():
    intervals = {bootstrap_interval(VALUES, mean, seed=s, resamples=7) for s in range(8)}
    assert len(intervals) > 1


def test_bootstrap_interval_brackets_the_sample_statistic():
    low, high = bootstrap_interval(VALUES, mean, seed=1, resamples=2000)
    assert low <= mean(VALUES) <= high
    assert low < high


def test_bootstrap_of_constant_data_is_degenerate():
    assert bootstrap_interval([4.0] * 6, mean, seed=3, resamples=200) == (4.0, 4.0)


def test_bootstrap_rejects_bad_arguments():
    with pytest.raises(ValueError):
        bootstrap_interval([], mean, seed=1)
    with pytest.raises(ValueError):
        bootstrap_interval(VALUES, mean, seed=1, resamples=0)
    with pytest.raises(ValueError):
        bootstrap_interval(VALUES, mean, seed=1, confidence=1.0)


# ---- Cohen's kappa -----------------------------------------------------------
def labels(yes_yes: int, yes_no: int, no_yes: int, no_no: int):
    a = ["y"] * (yes_yes + yes_no) + ["n"] * (no_yes + no_no)
    b = ["y"] * yes_yes + ["n"] * yes_no + ["y"] * no_yes + ["n"] * no_no
    return a, b


def test_kappa_matches_the_textbook_two_by_two_example():
    """50 items: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no.
    observed = 35/50 = 0.70; chance = 0.5*0.6 + 0.5*0.4 = 0.50; kappa = 0.40."""
    from evaluation.metrics.stats import cohens_kappa

    a, b = labels(20, 5, 10, 15)
    assert cohens_kappa(a, b) == pytest.approx(0.4, abs=1e-12)


def test_kappa_is_one_for_perfect_agreement_and_symmetric():
    from evaluation.metrics.stats import cohens_kappa

    a = ["real issue", "not an issue", "unclear", "real issue"]
    assert cohens_kappa(a, list(a)) == 1.0
    a, b = labels(20, 5, 10, 15)
    assert cohens_kappa(a, b) == cohens_kappa(b, a)


def test_kappa_is_zero_when_agreement_is_only_what_chance_predicts():
    from evaluation.metrics.stats import cohens_kappa

    a, b = labels(9, 9, 9, 9)  # each labeler says yes half the time, independently
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=1e-12)


def test_kappa_is_negative_when_labelers_systematically_disagree():
    from evaluation.metrics.stats import cohens_kappa

    a, b = labels(0, 10, 10, 0)
    assert cohens_kappa(a, b) == pytest.approx(-1.0, abs=1e-12)


def test_kappa_handles_three_categories():
    from evaluation.metrics.stats import cohens_kappa

    a = ["r", "r", "r", "n", "n", "u", "u", "n", "r", "n"]
    b = ["r", "r", "n", "n", "n", "u", "r", "n", "r", "u"]
    # observed 7/10; chance 0.4*0.4 + 0.4*0.4 + 0.2*0.2 = 0.36 -> (0.7-0.36)/0.64
    assert cohens_kappa(a, b) == pytest.approx((0.7 - 0.36) / 0.64, abs=1e-12)


def test_kappa_is_undefined_not_zero_or_one_when_there_is_nothing_to_agree_about():
    from evaluation.metrics.stats import cohens_kappa

    assert cohens_kappa([], []) is None
    assert cohens_kappa(["n"] * 8, ["n"] * 8) is None  # both said the same thing every time


def test_kappa_rejects_mismatched_lengths():
    from evaluation.metrics.stats import cohens_kappa

    with pytest.raises(ValueError):
        cohens_kappa(["a"], ["a", "b"])
