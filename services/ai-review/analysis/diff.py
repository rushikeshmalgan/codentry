"""Which lines of a file did the pull request add or change?

Two sources, in order of preference:

1. GitHub's own per-file `patch` (the unified-diff hunks returned by the
   "list pull request files" API) — authoritative, because it is the same
   diff a reviewer sees on the PR page.
2. A local `difflib` comparison of base and head content — used only when
   GitHub omits the patch (very large diffs) or when analyzing local files.

If neither can be produced the result is `available=False` and callers must
not pretend a finding is inside or outside the diff.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# Above this many lines a local difflib comparison can take unreasonably long
# on adversarial input, so it is not attempted.
MAX_LINES_FOR_LOCAL_DIFF = 4_000

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class FileDiff:
    """Head-side (1-based) line numbers that the change added or modified."""

    added_lines: frozenset[int]
    available: bool = True
    source: str = "none"  # "github_patch" | "difflib" | "new_file" | "none"

    def touches(self, start_line: int, end_line: int) -> bool:
        return any(line in self.added_lines for line in range(start_line, end_line + 1))


UNAVAILABLE = FileDiff(added_lines=frozenset(), available=False, source="none")


def parse_patch(patch: str) -> FileDiff:
    """Parses unified-diff hunks (GitHub `patch`) into head-side added lines."""
    added: set[int] = set()
    new_line = 0
    in_hunk = False

    for raw in patch.split("\n"):
        header = _HUNK_HEADER.match(raw)
        if header:
            new_line = int(header.group(3))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            added.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        elif raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        else:  # context line (leading space) or blank context
            new_line += 1

    return FileDiff(added_lines=frozenset(added), available=True, source="github_patch")


def diff_from_contents(base: str | None, head: str) -> FileDiff:
    """Local fallback: lines of `head` that are not matched in `base`."""
    head_lines = head.split("\n")
    if base is None:
        return FileDiff(
            added_lines=frozenset(range(1, len(head_lines) + 1)), available=True, source="new_file"
        )

    base_lines = base.split("\n")
    if len(base_lines) > MAX_LINES_FOR_LOCAL_DIFF or len(head_lines) > MAX_LINES_FOR_LOCAL_DIFF:
        return UNAVAILABLE

    matcher = difflib.SequenceMatcher(a=base_lines, b=head_lines, autojunk=False)
    added: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            added.update(range(j1 + 1, j2 + 1))
    return FileDiff(added_lines=frozenset(added), available=True, source="difflib")


def build_file_diff(patch: str | None, base: str | None, head: str | None) -> FileDiff:
    """Picks the best available diff for one changed file."""
    if head is None:
        return UNAVAILABLE
    if base is None:
        return diff_from_contents(None, head)
    if patch:
        return parse_patch(patch)
    return diff_from_contents(base, head)
