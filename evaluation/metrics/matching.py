"""Matching findings to ground-truth defects — pure functions, no I/O.

A finding **hits** a defect when both point at the same file (the identity
path, i.e. the path at the head, so a renamed file matches under its new name)
and the finding's line range overlaps the defect's range widened by `k` lines
on each side. `k` is a tolerance, not a fudge factor, so results are reported
for every k in `TOLERANCES` (sensitivity), with `DEFAULT_TOLERANCE` as the
headline.

Definitions used for every arm, so arms are comparable:

- defect *detected*        at least one reported finding hits it        -> recall
- finding *true positive*  it hits at least one defect                  -> precision
- finding *false positive* it hits none                                 -> FP per PR
- *exactly located*        a true positive that also overlaps the defect
                           with k = 0 (it points at the defective lines)
                           -> location accuracy = exactly located / true positives
- *duplicate*              a finding whose identity_key was already reported
                           (the same problem reported again)
- findings per changed line  reported findings / lines the change added

Known limits, stated here so no number is over-read:

- Matching is by **location only**. It cannot tell whether the finding
  describes the defect or merely sits on the same line (e.g. an unused-variable
  warning on a mutated line counts as a hit). Adjudicating findings by hand is
  the later, more expensive step; until then precision here is an upper bound.
- Several findings on one defect all count as true positives (they are all
  "pointing at a real defect"); duplicates are reported separately.
- A `k` above 0 makes recall and precision look better; read the k = 0 row too.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

TOLERANCES: tuple[int, ...] = (0, 2, 5)
DEFAULT_TOLERANCE = 2


@dataclass(frozen=True)
class Span:
    """A located thing: a defect, or a finding an arm reported. 1-based, inclusive."""

    file: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class MatchResult:
    tolerance: int
    defects: int
    detected_defects: tuple[int, ...]  # indices into the defect list
    missed_defects: tuple[int, ...]
    reported: int
    true_positive_findings: tuple[int, ...]  # indices into the reported list
    false_positive_findings: tuple[int, ...]
    exactly_located_findings: tuple[int, ...]


def hits(finding: Span, defect: Span, tolerance: int = DEFAULT_TOLERANCE) -> bool:
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if finding.file != defect.file:
        return False
    return (
        finding.start_line <= defect.end_line + tolerance
        and finding.end_line >= defect.start_line - tolerance
    )


def match(
    reported: Sequence[Span], defects: Sequence[Span], tolerance: int = DEFAULT_TOLERANCE
) -> MatchResult:
    detected: set[int] = set()
    true_positive: list[int] = []
    exactly_located: list[int] = []

    for i, finding in enumerate(reported):
        hit_any = False
        exact_any = False
        for j, defect in enumerate(defects):
            if hits(finding, defect, tolerance):
                hit_any = True
                detected.add(j)
                if hits(finding, defect, 0):
                    exact_any = True
        if hit_any:
            true_positive.append(i)
        if exact_any:
            exactly_located.append(i)

    tp = set(true_positive)
    return MatchResult(
        tolerance=tolerance,
        defects=len(defects),
        detected_defects=tuple(sorted(detected)),
        missed_defects=tuple(j for j in range(len(defects)) if j not in detected),
        reported=len(reported),
        true_positive_findings=tuple(true_positive),
        false_positive_findings=tuple(i for i in range(len(reported)) if i not in tp),
        exactly_located_findings=tuple(exactly_located),
    )


def duplicate_count(identity_keys: Sequence[str]) -> int:
    """Findings beyond the first for each identity_key."""
    return len(identity_keys) - len(set(identity_keys))


def ratio(numerator: int, denominator: int) -> float | None:
    """None (not 0.0, not 1.0) when the denominator is empty: 'no data' is not a score."""
    return None if denominator == 0 else numerator / denominator
