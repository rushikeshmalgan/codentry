"""The core, standalone entry point: files in, normalized Finding[] out.

    changed files (local disk or, from app/review_runner.py, GitHub content)
                |
                v
        ephemeral workspace (analysis/workspace.py)
                |
        +-------+-------+
        |               |
        v               v
      ESLint          Semgrep
        |               |
        +-------+-------+
                |
                v
        normalize.py -> Finding[]

Nothing in this module, or anything it imports (workspace, eslint_runner,
semgrep_runner, normalize, finding), imports `app.*`, an AI SDK, or
`supabase` — see analysis/run.py and tests/test_analysis_zero_ai.py for how
that's actually verified rather than just claimed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from analysis.eslint_runner import run_eslint
from analysis.finding import Finding
from analysis.normalize import normalize_eslint_result, normalize_semgrep_result
from analysis.semgrep_runner import run_semgrep
from analysis.workspace import SourceFile, WorkspaceLimitError, materialize

logger = logging.getLogger("codentry.ai_review.analysis")

ToolStatus = Literal["ok", "timeout", "error", "skipped"]
OverallStatus = Literal["completed", "partial_failure", "failed"]


@dataclass
class StaticAnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    eslint_status: ToolStatus = "skipped"
    semgrep_status: ToolStatus = "skipped"
    eslint_error: str | None = None
    semgrep_error: str | None = None
    skipped_files: list[dict[str, str]] = field(default_factory=list)

    @property
    def overall_status(self) -> OverallStatus:
        eslint_ok = self.eslint_status in ("ok", "skipped")
        semgrep_ok = self.semgrep_status in ("ok", "skipped")
        if eslint_ok and semgrep_ok:
            return "completed"
        if eslint_ok or semgrep_ok:
            return "partial_failure"
        return "failed"

    @property
    def error_summary(self) -> str | None:
        parts = []
        if self.eslint_status not in ("ok", "skipped"):
            parts.append(f"eslint_{self.eslint_status}: {self.eslint_error}")
        if self.semgrep_status not in ("ok", "skipped"):
            parts.append(f"semgrep_{self.semgrep_status}: {self.semgrep_error}")
        return "; ".join(parts) if parts else None


def analyze_source_files(files: list[SourceFile]) -> StaticAnalysisResult:
    """Core entry point once content is already in memory as SourceFile[]
    (used directly by app/review_runner.py after fetching from GitHub).
    """
    try:
        with materialize(files) as workspace:
            relative_paths = [f.path for f in files]
            return _run_tools(workspace, relative_paths)
    except WorkspaceLimitError as exc:
        logger.warning("workspace_limit_rejected reason=%s", exc)
        return StaticAnalysisResult(
            eslint_status="error",
            semgrep_status="error",
            eslint_error=str(exc),
            semgrep_error=str(exc),
        )


def _run_tools(workspace: Path, relative_paths: list[str]) -> StaticAnalysisResult:
    findings: list[Finding] = []

    eslint_result = run_eslint(workspace, relative_paths)
    if eslint_result.status == "ok":
        for file_report in eslint_result.file_reports:
            findings.extend(normalize_eslint_result(file_report, workspace))
    elif eslint_result.status != "skipped":
        logger.warning(
            "eslint_run_failed status=%s reason=%s",
            eslint_result.status,
            eslint_result.error_message,
        )

    semgrep_result = run_semgrep(workspace, relative_paths)
    if semgrep_result.status == "ok":
        for raw in semgrep_result.results:
            findings.append(normalize_semgrep_result(raw, workspace))
    elif semgrep_result.status != "skipped":
        logger.warning(
            "semgrep_run_failed status=%s reason=%s",
            semgrep_result.status,
            semgrep_result.error_message,
        )

    return StaticAnalysisResult(
        findings=findings,
        eslint_status=eslint_result.status,
        semgrep_status=semgrep_result.status,
        eslint_error=eslint_result.error_message,
        semgrep_error=semgrep_result.error_message,
    )


def run_static_analysis(repo_path: str, changed_files: list[str]) -> StaticAnalysisResult:
    """The FR-2 entry point: given a local repo checkout and a list of
    repo-relative changed-file paths, read them from disk and analyze them.

    Missing files (already deleted, typo'd path) and binary/undecodable
    files are skipped, not treated as errors — they're recorded in
    `skipped_files` so the caller can see what didn't get analyzed and why.
    """
    root = Path(repo_path)
    files: list[SourceFile] = []
    skipped: list[dict[str, str]] = []

    for rel_path in changed_files:
        full_path = root / rel_path
        if not full_path.is_file():
            skipped.append({"path": rel_path, "reason": "missing"})
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": rel_path, "reason": "binary_or_undecodable"})
            continue
        files.append(SourceFile(path=rel_path, content=content))

    result = analyze_source_files(files)
    result.skipped_files = skipped
    return result
