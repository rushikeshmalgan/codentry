"""Runs ESLint against a materialized workspace.

Invokes `node <eslint>/bin/eslint.js ...` directly rather than the
node_modules/.bin/eslint shim — on Windows that shim is a .cmd file, and
subprocess execution of .cmd files without shell=True is unreliable/
platform-specific. Calling `node <script.js>` is unambiguous and identical
on every platform, and keeps `shell=False` (no shell metacharacter risk from
anything derived from repository content) satisfiable everywhere.

Config priority (see module docstring in static_analysis.py for the
security rationale): a repository-provided .eslintrc.* is tried first, with
--resolve-plugins-relative-to pointed at Codentry's own pinned baseline
install — so a repo config referencing a plugin outside that pinned set
fails to load (closed, safely) rather than triggering any attempt to
install or execute the repository's own tooling. On any failure, this falls
back to the baseline config outright.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("codentry.ai_review.analysis.eslint_runner")

ANALYZABLE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
TIMEOUT_SECONDS = 30
REPO_CONFIG_CANDIDATES = (
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    ".eslintrc",
)

_BASELINE_DIR = Path(__file__).parent / "eslint-baseline"
_BASELINE_CONFIG = _BASELINE_DIR / ".eslintrc.baseline.json"
_BASELINE_ESLINT_JS = _BASELINE_DIR / "node_modules" / "eslint" / "bin" / "eslint.js"

RunStatus = Literal["ok", "timeout", "error", "skipped"]


@dataclass
class EslintRunResult:
    status: RunStatus
    # ESLint's raw per-file JSON objects.
    file_reports: list[dict[str, Any]] = field(default_factory=list)
    used_repo_config: bool = False
    error_message: str | None = None


def find_repo_config(workspace: Path) -> Path | None:
    for name in REPO_CONFIG_CANDIDATES:
        candidate = workspace / name
        if candidate.is_file():
            return candidate
    return None


def run_eslint(workspace: Path, relative_paths: list[str]) -> EslintRunResult:
    target_paths = [p for p in relative_paths if Path(p).suffix in ANALYZABLE_EXTENSIONS]
    if not target_paths:
        return EslintRunResult(status="skipped")

    node = shutil.which("node")
    if node is None or not _BASELINE_ESLINT_JS.exists():
        return EslintRunResult(
            status="error",
            error_message="eslint baseline unavailable: node not on PATH or "
            "analysis/eslint-baseline has no node_modules (run `npm install` there)",
        )

    repo_config = find_repo_config(workspace)
    if repo_config is not None:
        result = _invoke(node, workspace, target_paths, repo_config)
        if result.status == "ok":
            result.used_repo_config = True
            return result
        logger.warning(
            "eslint_repo_config_unusable path=%s reason=%s", repo_config.name, result.error_message
        )

    return _invoke(node, workspace, target_paths, _BASELINE_CONFIG)


def _invoke(
    node: str, workspace: Path, target_paths: list[str], config_path: Path
) -> EslintRunResult:
    cmd = [
        node,
        str(_BASELINE_ESLINT_JS),
        "--no-eslintrc",
        "-c",
        str(config_path),
        "--resolve-plugins-relative-to",
        str(_BASELINE_DIR),
        "--no-error-on-unmatched-pattern",
        "--format",
        "json",
        *target_paths,
    ]

    env = {**os.environ, "NODE_NO_WARNINGS": "1"}

    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return EslintRunResult(
            status="timeout", error_message=f"eslint exceeded {TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        return EslintRunResult(status="error", error_message=f"failed to launch eslint: {exc}")

    stdout = proc.stdout.strip()
    if not stdout:
        return EslintRunResult(
            status="error",
            error_message=(
                f"eslint produced no output (exit {proc.returncode}): {proc.stderr[:300]}"
            ),
        )

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return EslintRunResult(
            status="error",
            error_message=(
                f"eslint produced non-JSON output (exit {proc.returncode}): {stdout[:300]}"
            ),
        )

    # Exit code 0 = clean, 1 = lint findings present (expected, not a tool
    # failure). Anything else alongside parseable JSON is unusual but the
    # JSON itself is still trustworthy, so we don't discard it.
    return EslintRunResult(status="ok", file_reports=parsed)
