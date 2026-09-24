"""The core, standalone entry point: files in, normalized Finding[] out.

    files (local disk or, from app/, a pinned GitHub snapshot)
                |
        prepare_files: drop unsafe paths, control files, non-analyzable
                       types, oversize files — each with a recorded reason
                |
        ephemeral workspace (analysis/workspace.py)  +  tool sandbox
                |
        +-------+-------+
        |               |
        v               v
      ESLint          Semgrep      (scrubbed env, no repo-supplied config)
        |               |
        +-------+-------+
                |
        normalize.py -> Finding[]   (secrets redacted)
                |
        identity.py  -> identity_key / dedup_hash (line-number independent)

Differential classification (new / existing / fixed) is a separate step,
analysis/differential.py, applied by app/ to two of these results.

Nothing in this module, or anything it imports, imports `app.*`, an AI SDK,
or `supabase` — see analysis/run.py and tests/test_analysis_cli.py for how
that's actually verified rather than just claimed here.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from analysis.eslint_runner import _BASELINE_ESLINT_JS, run_eslint
from analysis.finding import Finding
from analysis.identity import IDENTITY_VERSION, assign_identities
from analysis.limits import MAX_FINDINGS
from analysis.normalize import normalize_eslint_result, normalize_semgrep_result
from analysis.redact import redact_secrets
from analysis.semgrep_runner import _RULESET, run_semgrep
from analysis.subprocess_env import tool_sandbox
from analysis.trusted_config import TrustedOverlay, baseline_config_sha256
from analysis.workspace import (
    SKIP_BINARY,
    SKIP_MISSING,
    SKIP_SYMLINK,
    SKIP_UNSAFE_PATH,
    SourceFile,
    WorkspaceLimitError,
    is_incomplete_skip,
    materialize,
    prepare_files,
    unsafe_path_reason,
)

logger = logging.getLogger("codentry.ai_review.analysis")

ToolStatus = Literal["ok", "timeout", "error", "skipped"]
OverallStatus = Literal["completed", "partial_failure", "failed"]

SKIP_TOOL_ERROR = "tool_error"
SKIP_FINDINGS_TRUNCATED = "findings_truncated"


@dataclass
class StaticAnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    eslint_status: ToolStatus = "skipped"
    semgrep_status: ToolStatus = "skipped"
    eslint_error: str | None = None
    semgrep_error: str | None = None
    skipped_files: list[dict[str, str]] = field(default_factory=list)
    config_source: str = "baseline"
    overlay_sha256: str | None = None
    overlay_dropped: tuple[str, ...] = ()
    analyzed_paths: list[str] = field(default_factory=list)

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
    def analysis_complete(self) -> bool:
        """True only if every tool that ran succeeded AND nothing that should
        have been analyzed was skipped or truncated. A "completed" tool
        status alone is not enough to call a review complete."""
        return self.overall_status == "completed" and not any(
            is_incomplete_skip(entry) for entry in self.skipped_files
        )

    @property
    def incomplete_reasons(self) -> list[str]:
        reasons = sorted({e["reason"] for e in self.skipped_files if is_incomplete_skip(e)})
        if self.overall_status != "completed":
            reasons.insert(0, f"tool_{self.overall_status}")
        return reasons

    @property
    def error_summary(self) -> str | None:
        parts = []
        if self.eslint_status not in ("ok", "skipped"):
            parts.append(f"eslint_{self.eslint_status}: {self.eslint_error}")
        if self.semgrep_status not in ("ok", "skipped"):
            parts.append(f"semgrep_{self.semgrep_status}: {self.semgrep_error}")
        return "; ".join(parts) if parts else None

    def meta(self) -> dict[str, Any]:
        """Reproducibility metadata recorded with every run (analysis_meta)."""
        skipped_by_reason: dict[str, int] = {}
        for entry in self.skipped_files:
            skipped_by_reason[entry["reason"]] = skipped_by_reason.get(entry["reason"], 0) + 1
        return {
            "identity_version": IDENTITY_VERSION,
            "eslint_status": self.eslint_status,
            "semgrep_status": self.semgrep_status,
            "eslint_version": _eslint_version(),
            "semgrep_version": _semgrep_version(),
            "ruleset_sha256": _ruleset_sha256(),
            "baseline_config_sha256": baseline_config_sha256(),
            "config_source": self.config_source,
            "overlay_sha256": self.overlay_sha256,
            "overlay_dropped": list(self.overlay_dropped),
            "files_analyzed": len(self.analyzed_paths),
            "skipped_by_reason": skipped_by_reason,
            "analysis_complete": self.analysis_complete,
            "incomplete_reasons": self.incomplete_reasons,
        }


def _eslint_version() -> str | None:
    try:
        pkg = json.loads((_BASELINE_ESLINT_JS.parents[1] / "package.json").read_text("utf-8"))
        return str(pkg.get("version"))
    except (OSError, ValueError):
        return None


def _semgrep_version() -> str | None:
    try:
        return metadata.version("semgrep")
    except metadata.PackageNotFoundError:
        return None


def _ruleset_sha256() -> str | None:
    try:
        return hashlib.sha256(Path(_RULESET).read_bytes()).hexdigest()
    except OSError:
        return None


def analyze_source_files(
    files: list[SourceFile],
    overlay: TrustedOverlay | None = None,
    identity_scope: str = "",
    path_map: dict[str, str] | None = None,
) -> StaticAnalysisResult:
    """Core entry point once content is already in memory as SourceFile[]
    (used by app/ after fetching a pinned snapshot from GitHub).

    `overlay` is the sanitized configuration read from the trusted BASE
    commit (never from `files`); see analysis/trusted_config.py. `path_map`
    (base path -> head path) makes findings in a renamed file keep one
    identity across the rename; it is only meaningful for the base snapshot.
    """
    prepared = prepare_files(files)
    result = StaticAnalysisResult(skipped_files=list(prepared.skipped))
    if overlay is not None:
        result.overlay_sha256 = overlay.sha256
        result.overlay_dropped = overlay.dropped

    try:
        with materialize(prepared.files) as workspace, tool_sandbox() as sandbox:
            relative_paths = [f.path for f in prepared.files]
            result.analyzed_paths = relative_paths
            _run_tools(result, workspace, relative_paths, overlay, sandbox)
    except WorkspaceLimitError as exc:
        logger.warning("workspace_limit_rejected reason=%s", exc)
        result.eslint_status = "error"
        result.semgrep_status = "error"
        result.eslint_error = result.semgrep_error = str(exc)
        result.findings = []
        return result

    contents = {f.path: f.content for f in prepared.files}
    assign_identities(result.findings, contents, identity_scope, path_map)
    return result


def _run_tools(
    result: StaticAnalysisResult,
    workspace: Path,
    relative_paths: list[str],
    overlay: TrustedOverlay | None,
    sandbox,
) -> None:
    findings: list[Finding] = []

    eslint_result = run_eslint(workspace, relative_paths, overlay=overlay, sandbox=sandbox)
    result.config_source = eslint_result.config_source
    if eslint_result.status == "ok":
        for file_report in eslint_result.file_reports:
            findings.extend(normalize_eslint_result(file_report, workspace))
    elif eslint_result.status != "skipped":
        logger.warning(
            "eslint_run_failed status=%s reason=%s",
            eslint_result.status,
            eslint_result.error_message,
        )

    semgrep_result = run_semgrep(workspace, relative_paths, sandbox=sandbox)
    if semgrep_result.status == "ok":
        for raw in semgrep_result.results:
            findings.append(normalize_semgrep_result(raw, workspace))
        for path in semgrep_result.tool_error_paths:
            result.skipped_files.append({"path": path, "reason": SKIP_TOOL_ERROR})
    elif semgrep_result.status != "skipped":
        logger.warning(
            "semgrep_run_failed status=%s reason=%s",
            semgrep_result.status,
            semgrep_result.error_message,
        )

    if len(findings) > MAX_FINDINGS:
        findings.sort(key=lambda f: (f.file_path, f.start_line, f.title))
        findings = findings[:MAX_FINDINGS]
        result.skipped_files.append({"path": "*", "reason": SKIP_FINDINGS_TRUNCATED})

    result.findings = findings
    result.eslint_status = eslint_result.status
    result.semgrep_status = semgrep_result.status
    result.eslint_error = redact_secrets(eslint_result.error_message)
    result.semgrep_error = redact_secrets(semgrep_result.error_message)


def run_static_analysis(repo_path: str, changed_files: list[str]) -> StaticAnalysisResult:
    """The FR-2 entry point: given a local repo checkout and a list of
    repo-relative changed-file paths, read them from disk and analyze them.

    Missing files (already deleted, typo'd path) and binary/undecodable
    files are skipped, not treated as errors — they're recorded in
    `skipped_files` so the caller can see what didn't get analyzed and why.
    """
    root = Path(repo_path)
    resolved_root = root.resolve()
    files: list[SourceFile] = []
    skipped: list[dict[str, str]] = []

    for rel_path in changed_files:
        if unsafe_path_reason(rel_path) is not None:
            skipped.append({"path": rel_path, "reason": SKIP_UNSAFE_PATH})
            continue
        full_path = root / rel_path
        # A symlink in a checkout can point anywhere on this machine; never
        # follow one out of the repository.
        if full_path.is_symlink() or resolved_root not in full_path.resolve().parents:
            skipped.append({"path": rel_path, "reason": SKIP_SYMLINK})
            continue
        if not full_path.is_file():
            skipped.append({"path": rel_path, "reason": SKIP_MISSING})
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": rel_path, "reason": SKIP_BINARY})
            continue
        files.append(SourceFile(path=rel_path, content=content))

    result = analyze_source_files(files)
    result.skipped_files = skipped + result.skipped_files
    return result
