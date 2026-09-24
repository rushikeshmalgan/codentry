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
