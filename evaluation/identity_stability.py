"""Identity-stability experiment: does a finding keep its `identity_key` when the
code around it changes in ways that are not a change to the finding itself?

    python -m evaluation.identity_stability --cases evaluation/cases --out <file.json>

Finding identity (analysis/identity.py) is meant to answer "is this the same
problem in the same code?" without asking what line it is on: it hashes the
repository scope, tool, path, rule, normalized message, and the whitespace-
normalized text of the flagged lines. Differential analysis depends on that
(a pull request that merely shifts lines must not "create" findings). This
experiment checks the claim on real code instead of trusting the docstring.

Two transformations, applied to real head files that already have findings:

- ``line_shift``          three blank lines inserted at the top: every finding's
                          line number changes, the flagged code does not
- ``trailing_whitespace`` two spaces appended to every non-blank line: the flagged
                          lines' bytes change, their meaning does not

For each, the multiset of identity keys before and after is compared. A finding is
*stable* if its key is present on both sides (multiset intersection, so repeated
findings are counted correctly and no assumption is made about their order).
Findings whose key vanishes, or appears only afterwards, are reported, not hidden.

Limits (also in the report): only two transformations; only this ruleset
(eslint:recommended + @typescript-eslint/recommended + six Semgrep rules), none of
which is a whitespace/formatting rule; files come from this project's own corpora;
and stability of the key says nothing about whether the finding is *correct*.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from analysis.static_analysis import analyze_source_files
from analysis.workspace import SourceFile

SCHEMA = "codentry.eval.identity_stability/1"
CHUNK = 12
SHIFT_LINES = 3
SCOPE = "identity-stability"
SOURCE_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")
CASE_PREFIXES = ("bug-", "pr-")  # real code only; not the synthetic mutation corpus


def line_shift(text: str, blank_lines: int = SHIFT_LINES) -> str:
    """Insert blank lines before line 1: every later line moves down, no line's content changes."""
    return "\n" * blank_lines + text


def trailing_whitespace(text: str) -> str:
    """Two trailing spaces on every non-blank line. The line count is unchanged."""
    return "\n".join(line + "  " if line.strip() else line for line in text.split("\n"))


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "line_shift": line_shift,
    "trailing_whitespace": trailing_whitespace,
}


def compare_keys(before: list[str], after: list[str]) -> dict[str, Any]:
    """Multiset comparison of identity keys."""
    b, a = Counter(before), Counter(after)
    stable = sum((b & a).values())
    return {
        "before": len(before),
        "after": len(after),
        "stable": stable,
        "vanished": sum((b - a).values()),  # present before, gone after
        "appeared": sum((a - b).values()),  # absent before, present after
    }


class ExperimentError(RuntimeError):
    pass


def _analyze(files: list[SourceFile]) -> tuple[list[Any], dict[str, Any]]:
    """Findings for a batch of files, in chunks; any unhealthy chunk aborts (twice tried)."""
    findings: list[Any] = []
    meta: dict[str, Any] = {}
    for i in range(0, len(files), CHUNK):
        chunk = files[i : i + CHUNK]
        for attempt in (1, 2):
            result = analyze_source_files(chunk, None, SCOPE)
            healthy = (
                result.eslint_status == "ok"
                and result.semgrep_status == "ok"
                and result.analysis_complete
                and not result.skipped_files
            )
            if healthy:
                break
            if attempt == 2:
                raise ExperimentError(
                    f"analysis unhealthy for files {[f.path for f in chunk][:3]}...: "
                    f"eslint={result.eslint_status} semgrep={result.semgrep_status} "
                    f"reasons={result.incomplete_reasons}"
                )
        findings.extend(result.findings)
        meta = result.meta()
    return findings, meta


def run_experiment(files: list[SourceFile]) -> dict[str, Any]:
    """`files` are real source files (unique paths). Only those with a finding are used."""
    original, meta = _analyze(files)
    with_findings = sorted({f.file_path for f in original})
    by_path = {f.path: f for f in files}
    selected = [by_path[p] for p in with_findings]
    keys_before = [f.identity_key for f in original]

    transforms: dict[str, Any] = {}
    for name, transform in TRANSFORMS.items():
        transformed = [SourceFile(f.path, transform(f.content)) for f in selected]
        after, _ = _analyze(transformed)
        row = compare_keys(keys_before, [f.identity_key for f in after])
        # what happened to the ones that did not survive, by rule (never hidden)
        before_c, after_c = Counter(keys_before), Counter(f.identity_key for f in after)
        rule_of = {f.identity_key: f"{f.source}:{f.title}" for f in [*original, *after]}
        row["vanished_by_rule"] = dict(
            sorted(Counter(rule_of[k] for k in (before_c - after_c).elements()).items())
        )
        row["appeared_by_rule"] = dict(
            sorted(Counter(rule_of[k] for k in (after_c - before_c).elements()).items())
        )
        row["stable_fraction"] = row["stable"] / row["before"] if row["before"] else None
        transforms[name] = row

    head = meta
    return {
        "schema": SCHEMA,
        "files_examined": len(files),
        "files_with_findings": len(selected),
        "findings_before": len(keys_before),
        "files_used": with_findings,
        "shift_lines": SHIFT_LINES,
        "transforms": transforms,
        "tools": {
            key: head.get(key)
            for key in (
                "eslint_version", "semgrep_version", "ruleset_sha256", "baseline_config_sha256"
            )
        },
    }


def corpus_files(cases_dir: Path, limit: int | None = None) -> list[SourceFile]:
    """Every source file under head/ of the real-code cases, sorted, paths prefixed by case id."""
    out: list[SourceFile] = []
    for case_dir in sorted(p for p in cases_dir.iterdir() if p.name.startswith(CASE_PREFIXES)):
        head = case_dir / "head"
        candidates = (p for p in head.rglob("*") if p.is_file() and p.suffix in SOURCE_SUFFIXES)
        for path in sorted(candidates):
            relative = path.relative_to(head).as_posix()
            out.append(SourceFile(f"{case_dir.name}/{relative}", path.read_bytes().decode("utf-8")))
    return out[:limit] if limit else out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.identity_stability")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="JSON result file to write")
    parser.add_argument(
        "--limit", type=int, default=None, help="use only the first N files (testing)"
    )
    args = parser.parse_args(argv)
    try:
        files = corpus_files(args.cases, args.limit)
        if not files:
            raise ExperimentError("no bug-*/pr-* head files found")
        result = run_experiment(files)
    except (ExperimentError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(
        f"files examined {result['files_examined']}, with findings "
        f"{result['files_with_findings']}, findings {result['findings_before']}"
    )
    for name, row in result["transforms"].items():
        print(f"  {name}: stable {row['stable']}/{row['before']} "
              f"(vanished {row['vanished']}, appeared {row['appeared']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
