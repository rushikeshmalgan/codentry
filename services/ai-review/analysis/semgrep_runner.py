"""Runs Semgrep against a materialized workspace.

Uses only a local, repository-committed ruleset file
(analysis/semgrep-rules/baseline.yml) — deliberately NOT a Semgrep Registry
pack (`--config p/security-audit` etc.), which fetches rules over the
network on first use. Section 6 requires analysis to run with network
blocked; a bundled local ruleset is the only way to actually satisfy that
rather than assert it.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("codentry.ai_review.analysis.semgrep_runner")

TIMEOUT_SECONDS = 30
_RULESET = Path(__file__).parent / "semgrep-rules" / "baseline.yml"

RunStatus = Literal["ok", "timeout", "error", "skipped"]


@dataclass
class SemgrepRunResult:
    status: RunStatus
    results: list[dict[str, Any]] = field(default_factory=list)  # Semgrep's raw results[] entries
    error_message: str | None = None


def run_semgrep(workspace: Path, relative_paths: list[str]) -> SemgrepRunResult:
    if not relative_paths:
        return SemgrepRunResult(status="skipped")

    semgrep_bin = shutil.which("semgrep")
    if semgrep_bin is None:
        return SemgrepRunResult(
            status="error",
            error_message="semgrep not found on PATH — install it in the service's virtualenv "
            "(`pip install semgrep`, already in requirements.txt)",
        )
    if not _RULESET.exists():
        return SemgrepRunResult(status="error", error_message=f"ruleset missing: {_RULESET}")

    cmd = [
        semgrep_bin,
        "--config",
        str(_RULESET),
        "--json",
        "--quiet",
        "--metrics",
        "off",
        *relative_paths,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return SemgrepRunResult(
            status="timeout", error_message=f"semgrep exceeded {TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        return SemgrepRunResult(status="error", error_message=f"failed to launch semgrep: {exc}")

    stdout = proc.stdout.strip()
    if not stdout:
        return SemgrepRunResult(
            status="error",
            error_message=(
                f"semgrep produced no output (exit {proc.returncode}): {proc.stderr[:300]}"
            ),
        )

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return SemgrepRunResult(
            status="error",
            error_message=(
                f"semgrep produced non-JSON output (exit {proc.returncode}): {stdout[:300]}"
            ),
        )

    tool_errors = parsed.get("errors") or []
    if tool_errors:
        logger.warning("semgrep_reported_errors count=%d", len(tool_errors))

    return SemgrepRunResult(status="ok", results=parsed.get("results", []))
