"""The normalized Finding shape — the boundary every static-analysis result
(and, from a later phase, every AI result) must cross before it's persisted
or posted anywhere. Mirrors packages/schemas/review.schema.json exactly.

Identity (Phase 0): `identity_key` and `dedup_hash` are computed by
analysis/identity.py and deliberately do NOT depend on line numbers — see
that module for what they do depend on and why. The old line-number-based
`compute_dedup_hash(source, file, start, end, rule)` is gone: it changed
whenever unrelated code above a finding was edited, so a PR that merely
shifted lines would have "created" findings that were already there.

Differential fields (`change_status`, `moved`, `in_diff`, `base_start_line`)
are only meaningful for findings produced by analysis/differential.py; the
standalone CLI leaves them at their defaults (`change_status=None`, meaning
"not classified against a base").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Source = Literal["ESLINT", "SEMGREP", "AI"]
Category = Literal[
    "correctness", "security", "logic", "cross_file", "architecture", "performance", "style"
]
Severity = Literal["critical", "high", "medium", "low", "info"]
# "new"      present at the PR head, absent at the base
# "existing" present at both (pre-existing; NOT the PR's fault)
# "fixed"    present at the base, gone at the head (removed by the PR)
ChangeStatus = Literal["new", "existing", "fixed"]


class Finding(BaseModel):
    source: Source
    category: Category
    severity: Severity
    confidence: float | None = None
    title: str
    description: str
    file_path: str
    start_line: int
    end_line: int
    suggestion: str | None = None
    reasoning: str | None = None
    evidence_span: str | None = None
    dedup_hash: str = ""
    identity_key: str | None = None
    change_status: ChangeStatus | None = None
    moved: bool = False
    in_diff: bool = False
    base_start_line: int | None = None
