"""Scrubbed environment and bounded execution for analysis subprocesses.

Before Phase 0, ESLint inherited the service's full environment (Supabase
service-role key, GitHub App private key, internal webhook secret, ...) and
Semgrep did too. Anything that could execute repository-influenced code in
those processes could read every secret. Now:

- the child environment is built from an explicit allowlist, never copied
  from os.environ wholesale;
- HOME / TEMP point at a throwaway sandbox directory, so tool caches and
  settings files never touch the service's real home;
- NODE_OPTIONS is set explicitly (an inherited `--require` would otherwise
  be code injection) and other tool env vars are pinned;
- on timeout the whole process tree is killed, not just the direct child
  (Semgrep spawns semgrep-core).

What this does NOT do: it is not a container or network sandbox. See
docs/architecture.md "Remaining risks".
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from analysis.limits import NODE_MAX_OLD_SPACE_MB, TOOL_MAX_OUTPUT_BYTES

# The only variables copied from the service's own environment. PATH is
# needed to locate node/semgrep; the Windows entries are required for the
# runtimes to start at all. None of these carry credentials.
_PASSTHROUGH = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)


class ToolTimeoutError(RuntimeError):
    """The tool exceeded its wall-clock budget and its process tree was killed."""


class ToolOutputTooLargeError(RuntimeError):
    """The tool produced more output than the configured ceiling."""


@dataclass(frozen=True)
class ToolProcessResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ToolSandbox:
    root: Path
    home: Path
    tmp: Path
    config_dir: Path


@contextmanager
def tool_sandbox() -> Iterator[ToolSandbox]:
    """A throwaway directory tree outside the analysis workspace.

    Holds HOME, TEMP, and generated tool configuration, so nothing the tools
    write (and nothing Codentry generates for them) is ever inside the
    directory the untrusted repository files live in.
    """
    root = Path(tempfile.mkdtemp(prefix="codentry-tool-"))
    try:
        home = root / "home"
        tmp = root / "tmp"
        config_dir = root / "config"
        for d in (home, tmp, config_dir):
            d.mkdir()
        yield ToolSandbox(root=root, home=home, tmp=tmp, config_dir=config_dir)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scrubbed_env(
    sandbox: ToolSandbox | None = None,
    extra: Mapping[str, str] | None = None,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Builds the child environment from the allowlist. Never starts from a copy."""
    source = os.environ if source_env is None else source_env
    env: dict[str, str] = {k: source[k] for k in _PASSTHROUGH if k in source}

    if sandbox is not None:
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
            env[name] = str(sandbox.home)
        env["XDG_CACHE_HOME"] = str(sandbox.tmp)
        for name in ("TEMP", "TMP", "TMPDIR"):
            env[name] = str(sandbox.tmp)

    env.update(
        {
            "NODE_NO_WARNINGS": "1",
            "NODE_OPTIONS": f"--max-old-space-size={NODE_MAX_OLD_SPACE_MB}",
            "NO_COLOR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
        }
    )
    if extra:
        env.update(extra)
    return env


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_tool(
    cmd: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    max_output_bytes: int = TOOL_MAX_OUTPUT_BYTES,
) -> ToolProcessResult:
    """Runs `cmd` without a shell, with a closed stdin, in its own process
    group, killing the whole tree if it exceeds `timeout` seconds.

    Raises ToolTimeoutError / ToolOutputTooLargeError; OSError propagates if
    the executable cannot be launched (callers turn that into an "error"
    status rather than crashing the review).
    """
    kwargs: dict = {
        "cwd": cwd,
        "env": dict(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - argv list, shell=False, scrubbed env
    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(proc)
        proc.communicate()
        raise ToolTimeoutError(f"exceeded {timeout:g}s") from exc

    if len(stdout_b) > max_output_bytes or len(stderr_b) > max_output_bytes:
        raise ToolOutputTooLargeError(f"output exceeded {max_output_bytes} bytes")

    return ToolProcessResult(
        returncode=proc.returncode,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
    )
