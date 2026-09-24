"""Normalization: raw ESLint/Semgrep tool output -> Finding.

Both functions produce the same Finding shape from structurally different
inputs. Neither fabricates confidence, reasoning, or evidence_span — static
tools have none of those, so they're always left null (per the schema:
confidence/reasoning/evidence_span are AI-only concepts).

Free text that echoes repository content (a tool message can quote an
identifier or literal) is passed through analysis.redact so a committed
credential is not copied into Codentry's database or, later, a PR comment.

Identity (`identity_key`, `dedup_hash`) is NOT computed here: it needs the
file text and the full finding set (for occurrence indexes). See
analysis/identity.py::assign_identities, called by static_analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analysis.finding import Finding
from analysis.redact import redact_secrets

_ESLINT_SEVERITY_MAP = {2: "high", 1: "medium"}
_SEMGREP_SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
_CATEGORIES = {
    "correctness", "security", "logic", "cross_file", "architecture", "performance", "style",
}


def _to_repo_relative(path: str, workspace: Path) -> str:
    """Normalizes a tool-reported path to a forward-slash, workspace-relative path."""
    candidate = Path(path)
    try:
        rel = candidate.relative_to(workspace)
    except ValueError:
        try:
            rel = candidate.resolve().relative_to(workspace.resolve())
        except (ValueError, OSError):
            rel = candidate
    return str(rel).replace("\\", "/")


def normalize_eslint_result(file_report: dict[str, Any], workspace: Path) -> list[Finding]:
    """One ESLint file_report (one entry of the tool's top-level JSON array) -> Finding[]."""
    file_path = _to_repo_relative(file_report["filePath"], workspace)
    findings: list[Finding] = []

    for message in file_report.get("messages", []):
        rule_id = message.get("ruleId") or "eslint-fatal-error"
        severity = _ESLINT_SEVERITY_MAP.get(message.get("severity"), "medium")
        start_line = message.get("line") or 1
        end_line = message.get("endLine") or start_line
        description = redact_secrets(message.get("message", "").strip()) or rule_id

        findings.append(
            Finding(
                source="ESLINT",
                category="correctness",
                severity=severity,
                confidence=None,
                title=rule_id,
                description=description,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                suggestion=None,
                reasoning=None,
                evidence_span=None,
            )
        )

    return findings


def normalize_semgrep_result(result: dict[str, Any], workspace: Path) -> Finding:
    """One Semgrep results[] entry -> Finding."""
    check_id = result["check_id"]
    rule_id = check_id.rsplit(".", 1)[-1]

    extra = result.get("extra", {})
    severity = _SEMGREP_SEVERITY_MAP.get(extra.get("severity"), "medium")
    category = (extra.get("metadata") or {}).get("category", "security")
    if category not in _CATEGORIES:
        category = "security"

    file_path = _to_repo_relative(result["path"], workspace)
    start_line = result["start"]["line"]
    end_line = result["end"]["line"]

    return Finding(
        source="SEMGREP",
        category=category,
        severity=severity,
        confidence=None,
        title=rule_id,
        description=redact_secrets(extra.get("message", "").strip()) or rule_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        suggestion=None,
        reasoning=None,
        evidence_span=None,
    )
