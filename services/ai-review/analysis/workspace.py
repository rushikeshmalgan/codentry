"""Ephemeral, sandboxed analysis workspace.

Source code under analysis is untrusted. It is written to a temporary
directory and only ever passed to ESLint/Semgrep as *data* (a path to read
text from) — nothing in this module executes, imports, or evaluates it. The
workspace is always cleaned up, including when analysis raises.

Phase 0 hardening (each item has a proof-of-concept test in
tests/test_security_poc.py):

- Paths are validated as *relative, plain* paths: no absolute/drive/UNC
  paths, no `..`, no backslashes, colons (NTFS alternate streams), control
  characters, Windows reserved device names, or trailing dot/space.
- Tool control files (`.eslintrc*`, `.eslintignore`, `.semgrepignore`,
  `package.json`, ...) are NEVER written. A pull request must not be able to
  configure, extend, or silence the tools that review it.
- Files are written as raw bytes, so line numbering matches git exactly
  (text-mode writes on Windows would turn `\\n` into `\\r\\n`).
- The final on-disk location is re-checked to be inside the workspace.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from analysis.limits import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_PATH_CHARS,
    MAX_TOTAL_BYTES,
)

logger = logging.getLogger("codentry.ai_review.analysis.workspace")

# Kept under their Phase 3 names: existing callers and tests import them.
MAX_FILE_SIZE_BYTES = MAX_FILE_BYTES

ANALYZABLE_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})

# Skip reasons. Benign reasons mean "nothing to analyze here"; the others
# mean a file that SHOULD have been analyzed was not, so the run must be
# reported as incomplete (see is_incomplete_skip).
SKIP_NOT_ANALYZABLE = "not_analyzable_type"
SKIP_CONTROL_FILE = "control_file"
SKIP_VENDORED = "vendored_or_metadata"
SKIP_UNSAFE_PATH = "unsafe_path"
SKIP_TOO_LARGE = "too_large"
SKIP_PATH_CONFLICT = "path_conflict"
SKIP_DUPLICATE = "duplicate_path"
SKIP_MISSING = "missing"
SKIP_BINARY = "binary_or_undecodable"
SKIP_FETCH_FAILED = "fetch_failed"
SKIP_SYMLINK = "symlink_or_special"
SKIP_BLOB_MISMATCH = "blob_mismatch"
SKIP_DELETED = "deleted"
SKIP_BASE_UNAVAILABLE = "base_unavailable"

_BENIGN_SKIP_REASONS = frozenset(
    {SKIP_NOT_ANALYZABLE, SKIP_CONTROL_FILE, SKIP_VENDORED, SKIP_DELETED}
)

_CONTROL_BASENAME = re.compile(
    r"""(?ix)^(
        \.eslintrc(\..+)?
      | \.eslintignore
      | \.eslintcache
      | eslint\.config\.\w+
      | \.semgrepignore
      | \.semgrep(\.ya?ml)?
      | semgrep\.ya?ml
      | \.gitignore
      | \.gitattributes
      | \.gitmodules
      | \.npmrc
      | \.yarnrc(\..+)?
      | \.nvmrc
      | package(-lock)?\.json
      | npm-shrinkwrap\.json
      | yarn\.lock
      | pnpm-lock\.yaml
      | (ts|js)config(\..+)?\.json
    )$"""
)
_CONTROL_DIRS = frozenset({".semgrep", ".git"})
_VENDORED_DIRS = frozenset({"node_modules"})
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class WorkspaceLimitError(ValueError):
    """Raised when input exceeds a hard safety limit or is structurally unsafe."""


@dataclass(frozen=True)
class SourceFile:
    """A single file to be analyzed: a repo-relative path plus its text content."""

    path: str
    content: str


@dataclass
class PreparedFiles:
    files: list[SourceFile] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def unsafe_path_reason(path: str) -> str | None:
    """Returns why `path` cannot be safely materialized, or None if it is fine."""
    if not path:
        return "empty path"
    if len(path) > MAX_PATH_CHARS:
        return "path too long"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return "control character in path"
    if "\\" in path:
        return "backslash in path"
    if ":" in path:
        return "colon in path (drive letter or alternate data stream)"
    if path.startswith("/") or _DRIVE_PREFIX.match(path):
        return "absolute path"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return "empty, '.', or '..' path component"
        if part != part.rstrip(" ."):
            return "path component ends with a space or dot"
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            return "reserved device name in path"
    return None


def is_control_file(path: str) -> bool:
    parts = path.split("/")
    if any(p in _CONTROL_DIRS for p in parts[:-1]):
        return True
    return bool(_CONTROL_BASENAME.match(parts[-1]))


def is_vendored(path: str) -> bool:
    return any(p in _VENDORED_DIRS for p in path.split("/")[:-1])


def is_analyzable(path: str) -> bool:
    return PurePosixPath(path).suffix in ANALYZABLE_EXTENSIONS


def is_incomplete_skip(entry: dict[str, str]) -> bool:
    """True if this skipped file means the analysis did NOT cover something
    it should have. Skipping a README or a lockfile is not incompleteness."""
    reason = entry.get("reason", "")
    if reason in _BENIGN_SKIP_REASONS:
        return False
    if reason == SKIP_BINARY and not is_analyzable(entry.get("path", "")):
        return False
    return True


def prepare_files(files: list[SourceFile]) -> PreparedFiles:
    """Filters `files` down to what may be written and analyzed, recording a
    reason for everything dropped. Hostile or ambiguous input is dropped with
    a reason — it is never partially processed and never silently ignored.
    """
    prepared = PreparedFiles()
    seen: set[str] = set()

    for f in files:
        reason = unsafe_path_reason(f.path)
        if reason is not None:
            prepared.skipped.append({"path": f.path, "reason": SKIP_UNSAFE_PATH})
            logger.warning("workspace_unsafe_path_skipped detail=%s", reason)
            continue
        if is_control_file(f.path):
            prepared.skipped.append({"path": f.path, "reason": SKIP_CONTROL_FILE})
            continue
        if is_vendored(f.path):
            prepared.skipped.append({"path": f.path, "reason": SKIP_VENDORED})
            continue
        if not is_analyzable(f.path):
            prepared.skipped.append({"path": f.path, "reason": SKIP_NOT_ANALYZABLE})
            continue
        if f.path in seen:
            prepared.skipped.append({"path": f.path, "reason": SKIP_DUPLICATE})
            continue
        if len(f.content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
            prepared.skipped.append({"path": f.path, "reason": SKIP_TOO_LARGE})
            continue
        seen.add(f.path)
        prepared.files.append(f)

    # `a` (a file) and `a/b.js` (inside it) cannot both exist on a filesystem.
    kept: list[SourceFile] = []
    kept_paths = {f.path for f in prepared.files}
    for f in prepared.files:
        parents = [str(p) for p in PurePosixPath(f.path).parents if str(p) != "."]
        if any(parent in kept_paths for parent in parents):
            prepared.skipped.append({"path": f.path, "reason": SKIP_PATH_CONFLICT})
        else:
            kept.append(f)
    prepared.files = kept
    return prepared


def enforce_limits(files: list[SourceFile]) -> None:
    """Hard, run-failing limits and structural checks (defense in depth: the
    normal path goes through prepare_files first and never trips these)."""
    if len(files) > MAX_FILES:
        raise WorkspaceLimitError(f"too many changed files: {len(files)} > {MAX_FILES}")
    total = 0
    for f in files:
        reason = unsafe_path_reason(f.path)
        if reason is not None:
            raise WorkspaceLimitError(f"unsafe file path rejected: {f.path!r} ({reason})")
        size = len(f.content.encode("utf-8", errors="replace"))
        if size > MAX_FILE_BYTES:
            raise WorkspaceLimitError(
                f"file too large, skipped for safety: {f.path} ({size} bytes > {MAX_FILE_BYTES})"
            )
        total += size
    if total > MAX_TOTAL_BYTES:
        raise WorkspaceLimitError(f"total size too large: {total} bytes > {MAX_TOTAL_BYTES}")


@contextmanager
def materialize(files: list[SourceFile]) -> Iterator[Path]:
    """Writes `files` into a fresh temp directory, preserving relative paths.

    Yields the workspace root. Always removes the directory on exit, success
    or failure — this is a context manager specifically so cleanup can't be
    forgotten on an exception path. Control files are silently not written.
    """
    enforce_limits(files)
    workspace_dir = Path(tempfile.mkdtemp(prefix="codentry-analysis-"))
    try:
        root = workspace_dir.resolve()
        for f in files:
            if is_control_file(f.path):
                continue
            target = workspace_dir / f.path
            resolved = target.resolve()
            if root not in resolved.parents:
                raise WorkspaceLimitError(f"path escapes workspace: {f.path!r}")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f.content.encode("utf-8", errors="replace"))
            except (FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
                raise WorkspaceLimitError(f"path conflict writing {f.path!r}") from exc
        yield workspace_dir
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)
