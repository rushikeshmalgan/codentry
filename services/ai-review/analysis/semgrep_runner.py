"""Runs Semgrep against a materialized workspace.

Uses only a local, repository-committed ruleset file
(analysis/semgrep-rules/production.yml) — deliberately NOT a Semgrep
Registry pack (`--config p/security-audit` etc.), which fetches rules over
the network on first use. Analysis must not depend on the network, and a
bundled local ruleset is the only way to actually satisfy that rather than
assert it.

That also means the "Semgrep arm" in any evaluation is Semgrep running
*Codentry's small hand-written ruleset*, not Semgrep's registry coverage.
See analysis/semgrep-rules/README.md — results must be labeled accordingly.

Hardening (tests/test_security_poc.py): a scrubbed environment; `--`, and
`./`-prefixed paths so file names are data, never options; `--disable-nosem`
so a PR cannot hide a finding with a `// nosemgrep` comment; `--no-git-ignore`;
memory, per-rule-timeout, and target-size ceilings; process tree killed on
timeout. No `.semgrepignore` is ever written into the workspace.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from analysis.limits import (
    MAX_FILE_BYTES,
    SEMGREP_MAX_MEMORY_MB,
    SEMGREP_RULE_TIMEOUT_SECONDS,
    SEMGREP_RULE_TIMEOUT_THRESHOLD,
    TOOL_TIMEOUT_SECONDS,
)
from analysis.redact import truncate_and_redact
from analysis.subprocess_env import (
    ToolOutputTooLargeError,
    ToolSandbox,
    ToolTimeoutError,
    run_tool,
    scrubbed_env,
    tool_sandbox,
)

logger = logging.getLogger("codentry.ai_review.analysis.semgrep_runner")

TIMEOUT_SECONDS = TOOL_TIMEOUT_SECONDS
RULES_DIR = Path(__file__).parent / "semgrep-rules"
_RULESET = RULES_DIR / "production.yml"

RunStatus = Literal["ok", "timeout", "error", "skipped"]


@dataclass
class SemgrepRunResult:
    status: RunStatus
    results: list[dict[str, Any]] = field(default_factory=list)  # Semgrep's raw results[] entries
    error_message: str | None = None
    # Workspace-relative paths Semgrep itself reported an error for (parse
    # failure, per-rule timeout, ...). Their results are unreliable, so the
    # run must not be presented as having fully covered them.
    tool_error_paths: list[str] = field(default_factory=list)


def cli_path(relative_path: str) -> str:
    """A workspace-relative path that can never be parsed as a CLI option."""
    return f"./{relative_path}"


def _find_semgrep() -> str | None:
    """Prefer the interpreter's own scripts dir (the service's virtualenv),
    then PATH — so a service started as `venv/bin/uvicorn` finds its own
    Semgrep even when the venv is not on PATH."""
    scripts_dir = str(Path(sys.executable).parent)
    search_path = os.pathsep.join([scripts_dir, os.environ.get("PATH", "")])
    return shutil.which("semgrep", path=search_path)


def build_command(semgrep_bin: str, relative_paths: list[str]) -> list[str]:
    return [
        semgrep_bin,
        "--config",
        str(_RULESET),
        "--json",
        "--quiet",
        "--metrics",
        "off",
        "--disable-version-check",
        "--disable-nosem",
        "--no-git-ignore",
        "--timeout",
        str(SEMGREP_RULE_TIMEOUT_SECONDS),
        "--timeout-threshold",
        str(SEMGREP_RULE_TIMEOUT_THRESHOLD),
        "--max-memory",
        str(SEMGREP_MAX_MEMORY_MB),
        "--max-target-bytes",
        str(MAX_FILE_BYTES),
        "--",
        *[cli_path(p) for p in relative_paths],
    ]


def run_semgrep(
    workspace: Path, relative_paths: list[str], sandbox: ToolSandbox | None = None
) -> SemgrepRunResult:
    if not relative_paths:
        return SemgrepRunResult(status="skipped")

    semgrep_bin = _find_semgrep()
    if semgrep_bin is None:
        return SemgrepRunResult(
            status="error",
            error_message="semgrep not found on PATH — install it in the service's virtualenv "
            "(`pip install semgrep`, already in requirements.txt)",
        )
    if not _RULESET.exists():
        return SemgrepRunResult(status="error", error_message=f"ruleset missing: {_RULESET}")

    if sandbox is not None:
        return _invoke(semgrep_bin, workspace, relative_paths, sandbox)
    with tool_sandbox() as own_sandbox:
        return _invoke(semgrep_bin, workspace, relative_paths, own_sandbox)


def _invoke(
    semgrep_bin: str, workspace: Path, relative_paths: list[str], sandbox: ToolSandbox
) -> SemgrepRunResult:
    cmd = build_command(semgrep_bin, relative_paths)
    env = scrubbed_env(sandbox)

    try:
        proc = run_tool(cmd, cwd=workspace, env=env, timeout=TIMEOUT_SECONDS)
    except ToolTimeoutError:
        return SemgrepRunResult(
            status="timeout", error_message=f"semgrep exceeded {TIMEOUT_SECONDS}s"
        )
    except ToolOutputTooLargeError as exc:
        return SemgrepRunResult(status="error", error_message=f"semgrep {exc}")
    except OSError as exc:
        return SemgrepRunResult(
            status="error", error_message=f"failed to launch semgrep: {type(exc).__name__}"
        )

    stdout = proc.stdout.strip()
    if not stdout:
        return SemgrepRunResult(
            status="error",
            error_message=(
                f"semgrep produced no output (exit {proc.returncode}): "
                f"{truncate_and_redact(proc.stderr)}"
            ),
        )

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return SemgrepRunResult(
            status="error",
            error_message=(
                f"semgrep produced non-JSON output (exit {proc.returncode}): "
                f"{truncate_and_redact(stdout)}"
            ),
        )

    tool_errors = parsed.get("errors") or []
    if tool_errors:
        logger.warning("semgrep_reported_errors count=%d", len(tool_errors))

    error_paths = sorted(
        {
            str(e["path"]).replace("\\", "/").removeprefix("./")
            for e in tool_errors
            if isinstance(e, dict) and e.get("path")
        }
    )
    return SemgrepRunResult(
        status="ok", results=parsed.get("results", []), tool_error_paths=error_paths
    )
