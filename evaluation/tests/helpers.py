"""Builders for throwaway case directories used by the harness tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_CASES = REPO_ROOT / "evaluation" / "cases"

BASE_SRC = "function add(a, b) {\n  return a + b;\n}\n"
HEAD_SRC = "function add(a, b) {\n  return a - b;\n}\n\nmodule.exports = { add };\n"

VALID_DOCUMENT: dict[str, Any] = {
    "schema_version": 1,
    "id": "t-001",
    "stratum": "fixture:unit",
    "language": "javascript",
    "license": "LicenseRef-project-authored",
    "source": {"kind": "handmade", "author": "tests"},
    "files": [{"path": "src/add.js", "status": "modified", "base": "base/src/add.js", "head": "head/src/add.js"}],
    "ground_truth": [
        {
            "file": "src/add.js",
            "start_line": 2,
            "end_line": 2,
            "kind": "logic",
            "provenance": "handmade",
            "verified_by": [{"method": "construction", "ref": "operator flipped in head"}],
        }
    ],
}


def document(**overrides: Any) -> dict[str, Any]:
    doc = copy.deepcopy(VALID_DOCUMENT)
    doc.update(overrides)
    return doc


def write_case(
    root: Path,
    doc: dict[str, Any] | None = None,
    *,
    base: str | None = BASE_SRC,
    head: str | None = HEAD_SRC,
    directory: str | None = None,
) -> Path:
    """Writes a case under `root` and returns its directory. `doc` defaults to a valid one."""
    doc = doc if doc is not None else document()
    case_dir = root / (directory or doc.get("id", "t-001"))
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_bytes(json.dumps(doc, indent=2).encode("utf-8"))
    if base is not None:
        (case_dir / "base" / "src").mkdir(parents=True, exist_ok=True)
        (case_dir / "base" / "src" / "add.js").write_bytes(base.encode("utf-8"))
    if head is not None:
        (case_dir / "head" / "src").mkdir(parents=True, exist_ok=True)
        (case_dir / "head" / "src" / "add.js").write_bytes(head.encode("utf-8"))
    return case_dir
