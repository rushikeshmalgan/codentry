"""Ephemeral, sandboxed analysis workspace.

Source code under analysis is untrusted. It is written to a temporary
directory and only ever passed to ESLint/Semgrep as *data* (a path to read
text from) — nothing in this module executes, imports, or evaluates it. The
workspace is always cleaned up, including when analysis raises.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("codentry.ai_review.analysis.workspace")

MAX_FILES = 200
# 500 KB — generous for a single source file, small enough to bound cost.
MAX_FILE_SIZE_BYTES = 500_000


class WorkspaceLimitError(ValueError):
    """Raised when the input exceeds a hard safety limit (too many files, one too large)."""


@dataclass(frozen=True)
class SourceFile:
    """A single file to be analyzed: a repo-relative path plus its text content."""

    path: str
    content: str


def _reject_unsafe_path(path: str) -> None:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise WorkspaceLimitError(f"unsafe file path rejected: {path!r}")


def enforce_limits(files: list[SourceFile]) -> None:
    if len(files) > MAX_FILES:
        raise WorkspaceLimitError(f"too many changed files: {len(files)} > {MAX_FILES}")
    for f in files:
        _reject_unsafe_path(f.path)
        size = len(f.content.encode("utf-8", errors="replace"))
        if size > MAX_FILE_SIZE_BYTES:
            raise WorkspaceLimitError(
                f"file too large, skipped for safety: {f.path} "
                f"({size} bytes > {MAX_FILE_SIZE_BYTES})"
            )


@contextmanager
def materialize(files: list[SourceFile]) -> Iterator[Path]:
    """Writes `files` into a fresh temp directory, preserving relative paths.

    Yields the workspace root. Always removes the directory on exit, success
    or failure — this is a context manager specifically so cleanup can't be
    forgotten on an exception path.
    """
    enforce_limits(files)
    workspace_dir = Path(tempfile.mkdtemp(prefix="codentry-analysis-"))
    try:
        for f in files:
            target = workspace_dir / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8", errors="replace")
        yield workspace_dir
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)
