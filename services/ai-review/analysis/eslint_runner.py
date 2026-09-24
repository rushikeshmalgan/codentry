"""Runs ESLint against a materialized workspace.

Invokes `node <eslint>/bin/eslint.js ...` directly rather than the
node_modules/.bin/eslint shim — on Windows that shim is a .cmd file, and
subprocess execution of .cmd files without shell=True is unreliable/
platform-specific. Calling `node <script.js>` is unambiguous and identical
on every platform, and keeps `shell=False` (no shell metacharacter risk from
anything derived from repository content) satisfiable everywhere.

Configuration is NEVER taken from the repository under analysis (see
analysis/trusted_config.py for why). ESLint runs with:

- `--no-eslintrc`            no config cascade; only the generated file below
- `-c <generated config>`    Codentry baseline (+ sanitized base-commit overlay),
                             written outside the workspace
- `--no-inline-config`       `/* eslint-disable */` and friends are ignored
- `--no-ignore`              `.eslintignore` and default ignores are ignored
- `--resolve-plugins-relative-to <baseline dir>`   only pinned plugins load
- `--`, and `./`-prefixed paths   file names are data, never options
- a scrubbed environment and a killed-on-timeout process tree
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from analysis.limits import TOOL_TIMEOUT_SECONDS
from analysis.redact import truncate_and_redact
from analysis.subprocess_env import (
    ToolOutputTooLargeError,
    ToolSandbox,
    ToolTimeoutError,
    run_tool,
    scrubbed_env,
    tool_sandbox,
)
from analysis.trusted_config import (
    BASELINE_DIR,
    TrustedOverlay,
    write_effective_config,
)
from analysis.workspace import ANALYZABLE_EXTENSIONS

logger = logging.getLogger("codentry.ai_review.analysis.eslint_runner")

TIMEOUT_SECONDS = TOOL_TIMEOUT_SECONDS

_BASELINE_ESLINT_JS = BASELINE_DIR / "node_modules" / "eslint" / "bin" / "eslint.js"

RunStatus = Literal["ok", "timeout", "error", "skipped"]


@dataclass
class EslintRunResult:
    status: RunStatus
    # ESLint's raw per-file JSON objects.
    file_reports: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    # "baseline" or "baseline+base_overlay"; never "repository".
    config_source: str = "baseline"


def cli_path(relative_path: str) -> str:
    """A workspace-relative path that can never be parsed as a CLI option."""
    return f"./{relative_path}"


def build_command(node: str, config_path: Path, relative_paths: list[str]) -> list[str]:
    return [
        node,
        str(_BASELINE_ESLINT_JS),
        "--no-eslintrc",
        "--no-inline-config",
        "--no-ignore",
        "-c",
        str(config_path),
        "--resolve-plugins-relative-to",
        str(BASELINE_DIR),
        "--no-error-on-unmatched-pattern",
        "--format",
        "json",
        "--",
        *[cli_path(p) for p in relative_paths],
    ]


def run_eslint(
    workspace: Path,
    relative_paths: list[str],
    overlay: TrustedOverlay | None = None,
    sandbox: ToolSandbox | None = None,
) -> EslintRunResult:
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

    config_source = "baseline+base_overlay" if overlay and not overlay.is_empty else "baseline"

    if sandbox is not None:
        return _invoke(node, workspace, target_paths, sandbox, overlay, config_source)
    with tool_sandbox() as own_sandbox:
        return _invoke(node, workspace, target_paths, own_sandbox, overlay, config_source)


def _invoke(
    node: str,
    workspace: Path,
    target_paths: list[str],
    sandbox: ToolSandbox,
    overlay: TrustedOverlay | None,
    config_source: str,
) -> EslintRunResult:
    config_path = write_effective_config(sandbox.config_dir, overlay)
    cmd = build_command(node, config_path, target_paths)
    env = scrubbed_env(sandbox)

    try:
        proc = run_tool(cmd, cwd=workspace, env=env, timeout=TIMEOUT_SECONDS)
    except ToolTimeoutError:
        return EslintRunResult(
            status="timeout",
            error_message=f"eslint exceeded {TIMEOUT_SECONDS}s",
            config_source=config_source,
        )
    except ToolOutputTooLargeError as exc:
        return EslintRunResult(
            status="error", error_message=f"eslint {exc}", config_source=config_source
        )
    except OSError as exc:
        return EslintRunResult(
            status="error",
            error_message=f"failed to launch eslint: {type(exc).__name__}",
            config_source=config_source,
        )

    stdout = proc.stdout.strip()
    if not stdout:
        return EslintRunResult(
            status="error",
            error_message=(
                f"eslint produced no output (exit {proc.returncode}): "
                f"{truncate_and_redact(proc.stderr)}"
            ),
            config_source=config_source,
        )

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return EslintRunResult(
            status="error",
            error_message=(
                f"eslint produced non-JSON output (exit {proc.returncode}): "
                f"{truncate_and_redact(stdout)}"
            ),
            config_source=config_source,
        )

    # Exit code 0 = clean, 1 = lint findings present (expected, not a tool
    # failure). Anything else alongside parseable JSON is unusual but the
    # JSON itself is still trustworthy, so we don't discard it.
    return EslintRunResult(status="ok", file_reports=parsed, config_source=config_source)
