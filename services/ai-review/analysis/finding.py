"""The normalized Finding shape — the boundary every static-analysis result
(and, from Phase 4, every AI result) must cross before it's persisted or
posted anywhere. Mirrors packages/schemas/review.schema.json exactly.

Note on a Phase 1 naming inconsistency fixed here: review.schema.json
originally used `file`, while the Phase 2 database schema (and this Phase 3
spec) both use `file_path`. Since the JSON schema's own README said it was
"not yet consumed by any code" as of Phase 1, this is fixed now — the JSON
schema file was updated to `file_path` to match, rather than carrying two
names for the same field into Phase 3.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel

Source = Literal["ESLINT", "SEMGREP", "AI"]
Category = Literal[
    "correctness", "security", "logic", "cross_file", "architecture", "performance", "style"
]
Severity = Literal["critical", "high", "medium", "low", "info"]


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
    dedup_hash: str


def compute_dedup_hash(
    source: str, file_path: str, start_line: int, end_line: int, rule_id: str
) -> str:
    """Deterministic hash identifying "the same underlying finding" across runs.

    Contributes: source, file_path, start_line, end_line, rule_id (the
    ESLint ruleId or Semgrep check_id — the closest thing either tool has to
    a stable identity for *what* was flagged, independent of the exact
    wording of the message).

    Deliberately excludes: timestamps, review_run_id, any random value, and
    the free-text message/description (which tools sometimes vary slightly
    run to run without the underlying issue changing) — a hash that included
    any of those would never recognize the same finding twice, defeating the
    entire point of a dedup key.
    """
    stable_key = f"{source}|{file_path}|{start_line}|{end_line}|{rule_id}"
    return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
