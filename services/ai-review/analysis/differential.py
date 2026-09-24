"""Differential analysis: "what did THIS pull request introduce?"

Static analysis of a whole file at the head reports every pre-existing
problem in every file the PR touched. Commenting on those would blame the PR
for code it did not write. The differential step compares findings from the
same tools and rules at the merge base and at the head:

    base findings ──┐
                    ├─ match by identity_key ─▶ new / existing / fixed
    head findings ──┘

- new       in the head, no counterpart in the base
- existing  matched; `moved=True` if the flagged code itself sits on a line
            the PR added (it was cut/pasted or re-added), otherwise it is
            simply unchanged (its line number may have drifted; that is not
            "moved")
- fixed     in the base, no counterpart at the head (the PR removed it)

Matching is by multiset per identity_key, not one-to-one by line, so several
identical findings (e.g. the same flagged statement repeated) are handled
without mis-attributing a newly added copy to the original. When the head has
more copies than the base, the extras chosen as "new" are the ones on
PR-added lines first, then the latest in the file.

A finding may only be classified if BOTH sides were analyzed. Callers must not
call this when the base analysis failed — an unclassifiable finding stays
`change_status=None` and is never treated as new (fail safe: silence over
noise).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from analysis.diff import FileDiff
from analysis.finding import Finding


@dataclass
class DifferentialResult:
    findings: list[Finding]  # head findings (new/existing) + fixed base findings
    new_count: int = 0
    existing_count: int = 0
    moved_count: int = 0
    fixed_count: int = 0


def _in_diff(finding: Finding, diffs: Mapping[str, FileDiff]) -> bool:
    diff = diffs.get(finding.file_path)
    return bool(diff and diff.available and diff.touches(finding.start_line, finding.end_line))


def classify(
    head_findings: list[Finding],
    base_findings: list[Finding],
    diffs: Mapping[str, FileDiff],
) -> DifferentialResult:
    """Returns classified copies; the inputs are not mutated.

    `diffs` maps HEAD paths to their FileDiff. Both finding lists must already
    have identities assigned (analysis.identity.assign_identities), with the
    base list identified through the rename map.
    """
    head_by_key: dict[str, list[Finding]] = defaultdict(list)
    base_by_key: dict[str, list[Finding]] = defaultdict(list)
    for f in head_findings:
        head_by_key[f.identity_key or f.dedup_hash].append(f)
    for f in base_findings:
        base_by_key[f.identity_key or f.dedup_hash].append(f)

    out: list[Finding] = []
    result = DifferentialResult(findings=out)

    for key, heads in head_by_key.items():
        bases = sorted(base_by_key.get(key, []), key=lambda f: f.start_line)
        matched = min(len(heads), len(bases))
        n_new = len(heads) - matched

        flagged = [(h, _in_diff(h, diffs)) for h in heads]
        # Extras go to lines the PR added first, then to later lines.
        by_newness = sorted(flagged, key=lambda pair: (not pair[1], -pair[0].start_line))
        new_ids = {id(pair[0]) for pair in by_newness[:n_new]}

        existing_heads = sorted(
            (pair for pair in flagged if id(pair[0]) not in new_ids),
            key=lambda pair: pair[0].start_line,
        )
        for (head, touched), base in zip(existing_heads, bases, strict=False):
            out.append(
                head.model_copy(
                    update={
                        "change_status": "existing",
                        "in_diff": touched,
                        "moved": touched,
                        "base_start_line": base.start_line,
                    }
                )
            )
            result.existing_count += 1
            result.moved_count += 1 if touched else 0

        for head, touched in flagged:
            if id(head) in new_ids:
                out.append(head.model_copy(update={"change_status": "new", "in_diff": touched}))
                result.new_count += 1

    for key, bases in base_by_key.items():
        head_count = len(head_by_key.get(key, []))
        # The earliest `head_count` base findings pair with existing heads;
        # whatever is left over was removed by the PR.
        for base in sorted(bases, key=lambda f: f.start_line)[head_count:]:
            out.append(base.model_copy(update={"change_status": "fixed"}))
            result.fixed_count += 1

    out.sort(key=lambda f: (f.file_path, f.start_line, f.title, f.change_status or ""))
    return result
