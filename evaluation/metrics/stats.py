"""Small-sample statistics for reporting results with their uncertainty.

Standard library only, deterministic (no hidden global RNG), so a report can be
regenerated exactly.

With the sample sizes this project can afford, intervals are wide: 6 of 20 is
30% but the 95% Wilson interval is 14.5%–51.9%. Every proportion should be
quoted with its interval.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from statistics import NormalDist


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    n == 0 returns (0.0, 1.0): with no observations every proportion is
    possible, and callers must not present that as a measured result.
    """
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("need 0 <= successes <= n")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if n == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    # The bounds at 0 and n successes are exactly 0 and 1; floating-point
    # rounding would otherwise leave e.g. 2.8e-17, which sits outside the estimate.
    low = 0.0 if successes == 0 else max(0.0, centre - half)
    high = 1.0 if successes == n else min(1.0, centre + half)
    return (low, high)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar test for paired binary outcomes.

    `only_a` = items arm A got right and arm B got wrong; `only_b` = the
    reverse. Items both got right or both got wrong carry no information and
    are not passed in. Returns the p-value under the null that the two arms are
    equally likely to win a discordant pair.
    """
    if only_a < 0 or only_b < 0:
        raise ValueError("counts must be >= 0")
    n = only_a + only_b
    if n == 0:
        return 1.0
    smaller = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(smaller + 1))
    return min(1.0, 2 * tail / 2**n)


def bootstrap_interval(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float],
    seed: int,
    confidence: float = 0.95,
    resamples: int = 10_000,
) -> tuple[float, float]:
    """Percentile bootstrap interval of `statistic` (e.g. the mean findings per PR).

    Deterministic: the same values, seed and resample count always give the same
    interval. The seed is a required argument so it cannot be forgotten and end
    up recorded as "unseeded".
    """
    if not values:
        raise ValueError("need at least one value")
    if resamples < 1:
        raise ValueError("resamples must be >= 1")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    rng = random.Random(seed)
    population = list(values)
    estimates = sorted(
        statistic(rng.choices(population, k=len(population))) for _ in range(resamples)
    )
    alpha = 1 - confidence
    low = estimates[int(math.floor(alpha / 2 * resamples))]
    high = estimates[min(resamples - 1, int(math.ceil((1 - alpha / 2) * resamples)) - 1)]
    return (low, high)


def cohens_kappa(labels_a: Sequence[str], labels_b: Sequence[str]) -> float | None:
    """Cohen's kappa for two labelers who labeled the same items.

    kappa = (p_observed - p_chance) / (1 - p_chance), where p_chance is the agreement
    expected if each labeler kept their own label frequencies but labeled at random.
    Returns None when kappa is undefined: no items, or both labelers used one single
    identical label for everything (p_chance == 1), where there is nothing to agree
    *about*. Never returns 0.0 or 1.0 for those cases.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("both labelers must label the same items")
    n = len(labels_a)
    if n == 0:
        return None
    observed = sum(a == b for a, b in zip(labels_a, labels_b, strict=True)) / n
    categories = set(labels_a) | set(labels_b)
    chance = sum(
        (labels_a.count(c) / n) * (labels_b.count(c) / n) for c in categories
    )
    if chance == 1.0:
        return None
    return (observed - chance) / (1.0 - chance)
