"""Head-side changed line ranges between two versions of a file — pure, no I/O.

This is the harness's single definition of "where did the change happen",
used to derive ground truth for generated and reversed-fix cases and to check
it in tests. It is an independent implementation (difflib) from git's diff;
importers require the two to agree before a case is accepted.
"""

from __future__ import annotations

import difflib

from evaluation.case import line_count


def changed_head_ranges(base: str, head: str) -> list[tuple[int, int]]:
    """1-based inclusive head line ranges of each changed hunk, in order.

    A pure deletion (lines present in base, absent from head) has no head lines;
    it is reported as the single line now sitting at the deletion point, clamped
    to the file, because that is where a reviewer would look for the missing code.
    """
    matcher = difflib.SequenceMatcher(a=base.split("\n"), b=head.split("\n"), autojunk=False)
    last = max(line_count(head), 1)
    ranges: list[tuple[int, int]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            line = min(j1 + 1, last)
            ranges.append((line, line))
        else:
            ranges.append((j1 + 1, min(j2, last)))
    return ranges


def single_hunk_range(base: str, head: str) -> tuple[int, int] | None:
    """The head range of the one changed hunk, or None if there is not exactly one."""
    ranges = changed_head_ranges(base, head)
    return ranges[0] if len(ranges) == 1 else None
