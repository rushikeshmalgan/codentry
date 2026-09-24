"""Loading and validating evaluation cases from disk.

A case directory looks like::

    evaluation/cases/<case-id>/
        case.json          validated against schema/case.schema.json
        base/...           file contents before the change
        head/...           file contents after the change

`load_case` returns a `Case` split into two parts on purpose:

- `CaseInputs`  — everything an arm may see (files and provenance metadata)
- `ground_truth` — the labeled defects, which an arm must never see

Arms receive only `CaseInputs`, so blinding is structural rather than a
convention: a future AI arm cannot leak the answer by accident because the
object it is handed does not contain it.

Everything here is data-in, data-out: no network, no tools, no clock.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schema" / "case.schema.json"
CASE_FILENAME = "case.json"

_UNKNOWN_SHA = "n/a"


class CaseError(ValueError):
    """A case directory is malformed. Never skipped silently: a run that quietly
    dropped a case would change the denominator of every metric."""


@dataclass(frozen=True)
class CaseFile:
    path: str  # path at the head — the identity path
    status: str  # added | modified | removed | renamed
    previous_path: str | None
    base_content: str | None
    head_content: str | None


@dataclass(frozen=True)
class CaseInputs:
    """What an arm is allowed to see. Deliberately has no ground truth."""

    id: str
    language: str
    base_sha: str
    head_sha: str
    files: tuple[CaseFile, ...]


@dataclass(frozen=True)
class Defect:
    file: str
    start_line: int
    end_line: int
    kind: str
    provenance: str
    verified_by: tuple[tuple[str, str], ...]  # (method, ref)


@dataclass(frozen=True)
class Case:
    id: str
    stratum: str
    inputs: CaseInputs
    ground_truth: tuple[Defect, ...]


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_document(document: object) -> list[str]:
    """Schema errors as stable, sorted strings (empty list = valid)."""
    errors = sorted(
        _schema_validator().iter_errors(document),
        key=lambda e: ([str(p) for p in e.absolute_path], e.message),
    )
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def line_count(text: str) -> int:
    """Number of lines as a text editor / git counts them (a trailing newline does
    not start another line)."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _read_text(case_dir: Path, relative: str, what: str) -> str:
    root = case_dir.resolve()
    target = case_dir / relative
    if target.is_symlink():
        raise CaseError(f"{what}: {relative!r} is a symlink")
    resolved = target.resolve()
    if root != resolved and root not in resolved.parents:
        raise CaseError(f"{what}: {relative!r} escapes the case directory")
    if not resolved.is_file():
        raise CaseError(f"{what}: {relative!r} does not exist")
    try:
        return resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseError(f"{what}: {relative!r} is not valid UTF-8") from exc


def load_case(case_dir: Path) -> Case:
    case_dir = Path(case_dir)
    document_path = case_dir / CASE_FILENAME
    if not document_path.is_file():
        raise CaseError(f"{case_dir.name}: missing {CASE_FILENAME}")
    try:
        document = json.loads(document_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CaseError(f"{case_dir.name}: {CASE_FILENAME} is not valid JSON ({exc})") from exc

    errors = validate_document(document)
    if errors:
        raise CaseError(f"{case_dir.name}: invalid case.json — " + "; ".join(errors))

    case_id = document["id"]
    if case_id != case_dir.name:
        raise CaseError(f"{case_dir.name}: id {case_id!r} must equal the directory name")

    files: list[CaseFile] = []
    seen_paths: set[str] = set()
    for entry in document["files"]:
        path = entry["path"]
        if path in seen_paths:
            raise CaseError(f"{case_id}: duplicate file path {path!r}")
        seen_paths.add(path)
        base = entry.get("base")
        head = entry.get("head")
        files.append(
            CaseFile(
                path=path,
                status=entry["status"],
                previous_path=entry.get("previous_path"),
                base_content=_read_text(case_dir, base, f"{case_id} base") if base else None,
                head_content=_read_text(case_dir, head, f"{case_id} head") if head else None,
            )
        )

    head_lines = {f.path: line_count(f.head_content) for f in files if f.head_content is not None}
    defects: list[Defect] = []
    for i, raw in enumerate(document["ground_truth"]):
        where = f"{case_id}: ground_truth[{i}]"
        if raw["file"] not in head_lines:
            raise CaseError(
                f"{where}: file {raw['file']!r} is not a changed file with head content"
            )
        if raw["start_line"] > raw["end_line"]:
            raise CaseError(f"{where}: start_line > end_line")
        if raw["end_line"] > head_lines[raw["file"]]:
            raise CaseError(
                f"{where}: end_line {raw['end_line']} is past the end of {raw['file']!r} "
                f"({head_lines[raw['file']]} lines)"
            )
        defects.append(
            Defect(
                file=raw["file"],
                start_line=raw["start_line"],
                end_line=raw["end_line"],
                kind=raw["kind"],
                provenance=raw["provenance"],
                verified_by=tuple((v["method"], v["ref"]) for v in raw["verified_by"]),
            )
        )

    source = document["source"]
    inputs = CaseInputs(
        id=case_id,
        language=document["language"],
        base_sha=source.get("base_sha", _UNKNOWN_SHA),
        head_sha=source.get("head_sha", _UNKNOWN_SHA),
        files=tuple(files),
    )
    return Case(id=case_id, stratum=document["stratum"], inputs=inputs, ground_truth=tuple(defects))


def discover_case_dirs(cases_dir: Path) -> list[Path]:
    """Sorted case directories (anything directly under `cases_dir` holding a case.json)."""
    cases_dir = Path(cases_dir)
    if not cases_dir.is_dir():
        raise CaseError(f"cases directory not found: {cases_dir}")
    return sorted(p for p in cases_dir.iterdir() if p.is_dir() and (p / CASE_FILENAME).is_file())


def manifest_sha256(case_dirs: list[Path]) -> str:
    """One hash over the exact bytes of every file of every case, so a run can say
    *which* case set it measured. Depends only on directory names, relative paths
    and file bytes (see evaluation/cases/.gitattributes for why bytes are stable)."""
    entries: list[tuple[str, str, str]] = []
    for case_dir in sorted(case_dirs, key=lambda p: p.name):
        for path in sorted(p for p in case_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(case_dir).as_posix()
            entries.append((case_dir.name, relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
