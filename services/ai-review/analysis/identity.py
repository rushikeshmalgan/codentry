"""Finding identity v2: "is this the same problem in the same code?" —
without asking what line it is on.

    identity_key = sha256(scope | source | path | rule | message | anchor)
    dedup_hash   = sha256(identity_key | occurrence_index)

- scope        the repository (a stable id string), so two repos never collide.
               Empty for the standalone CLI, which has no repository.
- source       ESLINT / SEMGREP / AI
- path         the file's path AT THE HEAD (a renamed file keeps one identity;
               base findings are mapped through the rename)
- rule         the tool's rule id (stored as Finding.title for static tools)
- message      whitespace/case-normalized; "line N" references stripped
- anchor       the flagged source text (whitespace-normalized), i.e. WHAT
               code was flagged rather than WHERE it is
- occurrence   index among findings with an identical identity_key in the
               same file, in line order — so two identical flagged lines are
               still distinct findings

Consequences (each is a test in tests/test_identity.py):
- inserting or deleting code ABOVE a finding does not change its identity;
- editing the flagged line itself does (it is different code — a "new"
  finding), which is the desired behavior for differential analysis;
- reformatting whitespace inside the flagged line does not.

Known limits: a finding whose anchor text is empty (e.g. a whole-file
message) falls back to path+rule+message+occurrence; refactors that rename
an identifier in the flagged line look like fixed+new; `identity_key`
collisions are only distinguished by occurrence order.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping

from analysis.finding import Finding

IDENTITY_VERSION = 2
_MAX_ANCHOR_CHARS = 240

_WS = re.compile(r"\s+")
_LINE_REF = re.compile(r"(?i)\blines?\s+\d+(?:\s*[-–]\s*\d+)?")


def normalize_message(message: str) -> str:
    collapsed = _WS.sub(" ", _LINE_REF.sub("line N", message)).strip()
    return collapsed.casefold()


def normalize_anchor(content: str | None, start_line: int, end_line: int) -> str:
    """The whitespace-normalized source text of lines [start_line, end_line]."""
    if not content or start_line < 1:
        return ""
    lines = content.split("\n")
    if start_line > len(lines):
        return ""
    end = min(max(end_line, start_line), len(lines))
    snippet = " ".join(lines[start_line - 1 : end])
    return _WS.sub(" ", snippet).strip()[:_MAX_ANCHOR_CHARS]


def compute_identity_key(
    scope: str, source: str, path: str, rule: str, message: str, anchor: str
) -> str:
    parts = [str(IDENTITY_VERSION), scope, source, path, rule, normalize_message(message), anchor]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def compute_dedup_hash(identity_key: str, occurrence_index: int) -> str:
    return hashlib.sha256(f"{identity_key}\x1f{occurrence_index}".encode()).hexdigest()


def assign_identities(
    findings: list[Finding],
    contents: Mapping[str, str],
    scope: str = "",
    path_map: Mapping[str, str] | None = None,
) -> None:
    """Sets identity_key and dedup_hash on every finding, in place.

    `contents` maps the finding's own file_path to the text it was found in.
    `path_map` maps a base-side path to the head-side path it should be
    identified under (renames); paths not in the map identify as themselves.
    Ordering is deterministic: findings are processed in (path, line, rule)
    order, so the same inputs always produce the same occurrence indexes.
    """
    counters: dict[str, int] = defaultdict(int)
    ordered = sorted(
        findings, key=lambda f: (f.file_path, f.start_line, f.end_line, f.source, f.title)
    )
    for finding in ordered:
        identity_path = (path_map or {}).get(finding.file_path, finding.file_path)
        anchor = normalize_anchor(
            contents.get(finding.file_path), finding.start_line, finding.end_line
        )
        key = compute_identity_key(
            scope, finding.source, identity_path, finding.title, finding.description, anchor
        )
        finding.identity_key = key
        finding.dedup_hash = compute_dedup_hash(key, counters[key])
        counters[key] += 1
