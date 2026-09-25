"""Builds mutation cases from evaluation/datasets/manifest.json.

    python -m evaluation.generators.build_cases --out evaluation/cases
    python -m evaluation.generators.build_cases --verify      # regenerate to a temp dir and diff

(from the repository root, with Node and the ESLint baseline install available —
the TypeScript parser used by sites.js lives there).

Reads only vendored files (no network). Every generated case directory is named
``mut-*``; hand-made fixture cases (``fx-*``) are never touched. Regenerating
from the same manifest, seed and TypeScript version reproduces every case byte
for byte — ``--verify`` proves it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.generators.mutate import (
    GENERATOR_ID,
    STRATUM_LOGIC,
    STRATUM_RULE_ALIGNED,
    GeneratorError,
    Mutant,
    derive_seed,
    generate_logic,
    generate_rule_aligned,
    typescript_version,
)

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
DEFAULT_MANIFEST = DATASETS / "manifest.json"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "cases"
CASE_PREFIX = "mut-"


@dataclass
class Stats:
    cases: int = 0
    per_file: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(manifest_dir: Path, repo: dict, entry: dict) -> str:
    """A vendored source, refused if its bytes no longer match the manifest."""
    path = manifest_dir / entry["vendored_as"]
    data = path.read_bytes()
    if _sha256(data) != entry["sha256"]:
        raise GeneratorError(f"{entry['vendored_as']}: sha256 differs from the manifest")
    return data.decode("utf-8")


def case_id(repo_id: str, slug: str, stratum: str, index: int) -> str:
    letter = "l" if stratum == STRATUM_LOGIC else "r"
    return f"{CASE_PREFIX}{repo_id}-{slug}-{letter}{index:02d}"


def case_document(
    repo: dict, entry: dict, mutant: Mutant, seed: int, cid: str
) -> dict[str, Any]:
    path = entry["path"]
    is_logic = mutant.stratum == STRATUM_LOGIC
    where = (
        f"line {mutant.start_line}"
        if mutant.start_line == mutant.end_line
        else f"lines {mutant.start_line}-{mutant.end_line}"
    )
    defect: dict[str, Any] = {
        "file": path,
        "start_line": mutant.start_line,
        "end_line": mutant.end_line,
        "kind": "logic" if is_logic else "security",
        "provenance": "mutation",
        "verified_by": [{"method": "construction", "ref": f"{GENERATOR_ID}:{mutant.operator}"}],
        "description": f"{mutant.operator} ({mutant.detail}) at {where}."
        + (" Equivalence unchecked." if is_logic else ""),
    }
    if is_logic:
        defect["equivalence"] = "unchecked"
    return {
        "schema_version": 1,
        "id": cid,
        "stratum": mutant.stratum,
        "language": entry["language"],
        "license": repo["license"],
        "source": {
            "kind": "generated",
            "generator": f"{GENERATOR_ID}:{mutant.operator}",
            "seed": seed,
            "origin": {"url": repo["url"], "commit": repo["commit"], "path": path},
        },
        "files": [
            {"path": path, "status": "modified", "base": f"base/{path}", "head": f"head/{path}"}
        ],
        "ground_truth": [defect],
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def generate(manifest_path: Path, out_dir: Path) -> Stats:
    manifest = load_manifest(manifest_path)
    params = manifest["generation"]
    actual_ts = typescript_version()
    if actual_ts != params["typescript"]:
        raise GeneratorError(
            f"TypeScript {actual_ts} differs from the manifest's {params['typescript']}: "
            "site enumeration may differ; review and update the manifest deliberately"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{CASE_PREFIX}*"):
        if stale.is_dir():
            shutil.rmtree(stale)

    stats = Stats()
    for repo in manifest["repositories"]:
        for entry in repo["files"]:
            base = read_source(manifest_path.parent, repo, entry)
            file_id = f"{repo['id']}/{entry['path']}"
            for stratum, generator, count in (
                (STRATUM_LOGIC, generate_logic, params["logic_per_file"]),
                (STRATUM_RULE_ALIGNED, generate_rule_aligned, params["rule_aligned_per_file"]),
            ):
                seed = derive_seed(params["global_seed"], file_id, stratum)
                result = generator(base, entry["path"], seed, count)
                stats.per_file[f"{file_id} [{stratum}]"] = {
                    "generated": len(result.mutants),
                    "requested": count,
                    "candidates": result.candidates,
                    "discarded": result.discarded,
                }
                for mutant in result.mutants:
                    cid = case_id(repo["id"], entry["slug"], stratum, mutant.index)
                    doc = case_document(repo, entry, mutant, seed, cid)
                    case_dir = out_dir / cid
                    _write(case_dir / "case.json", (json.dumps(doc, indent=2) + "\n").encode())
                    _write(case_dir / "base" / entry["path"], base.encode("utf-8"))
                    _write(case_dir / "head" / entry["path"], mutant.head_text.encode("utf-8"))
                    stats.cases += 1
    return stats


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0].startswith(CASE_PREFIX)
    }


def verify(manifest_path: Path, cases_dir: Path) -> list[str]:
    """Differences between the committed mutation cases and a fresh regeneration
    (empty list = byte-identical)."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp)
        generate(manifest_path, fresh_dir)
        fresh, committed = _tree(fresh_dir), _tree(cases_dir)
    problems = [f"missing from {cases_dir.name}: {p}" for p in sorted(set(fresh) - set(committed))]
    problems += [f"not produced by the generator: {p}" for p in sorted(set(committed) - set(fresh))]
    shared = sorted(set(fresh) & set(committed))
    problems += [f"bytes differ: {p}" for p in shared if fresh[p] != committed[p]]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.generators.build_cases")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--verify", action="store_true", help="regenerate to a temp dir and compare"
    )
    args = parser.parse_args(argv)
    try:
        if args.verify:
            problems = verify(args.manifest, args.out)
            for p in problems[:50]:
                print(p, file=sys.stderr)
            print("byte-identical" if not problems else f"{len(problems)} difference(s)")
            return 0 if not problems else 1
        stats = generate(args.manifest, args.out)
    except (GeneratorError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    short = {k: v for k, v in stats.per_file.items() if v["generated"] < v["requested"]}
    print(f"wrote {stats.cases} cases to {args.out}")
    for key, v in short.items():
        print(f"  short: {key}: {v['generated']}/{v['requested']} (discarded {v['discarded']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
