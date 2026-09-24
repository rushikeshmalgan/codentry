"""Standalone CLI proving FR-2: static analysis works with zero AI, zero
GitHub, zero Supabase, zero network dependency beyond what ESLint/Semgrep
themselves need (none, given a local ruleset).

Usage (run from services/ai-review, so the `analysis` package resolves):

    python -m analysis.run <repo_path> <file1> [file2 ...]

Example:

    python -m analysis.run analysis/fixtures eslint_sample.js semgrep_sample.js

Exit codes:
    0 - analysis ran (findings may or may not be present; a partial tool
        failure with the other tool still succeeding is still exit 0 —
        see "partial_failure" in the printed JSON's overall_status)
    2 - both tools failed/timed out/were unavailable; nothing was analyzed
    3 - usage error (missing arguments)

This module imports nothing beyond analysis.static_analysis, argparse,
json, and sys — deliberately, so "the CLI makes zero AI/GitHub/Supabase
calls" is true by construction, not by promise.
"""

from __future__ import annotations

import argparse
import json
import sys

from analysis.static_analysis import run_static_analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.run",
        description="Run Codentry's standalone static analysis (ESLint + Semgrep) "
        "against a local repository checkout. Makes no AI, GitHub, or Supabase calls.",
    )
    parser.add_argument("repo", help="Path to a local repository checkout")
    parser.add_argument("files", nargs="+", help="Repo-relative changed-file paths to analyze")
    args = parser.parse_args(argv)

    result = run_static_analysis(args.repo, args.files)

    output = {
        "overall_status": result.overall_status,
        "eslint_status": result.eslint_status,
        "semgrep_status": result.semgrep_status,
        "eslint_error": result.eslint_error,
        "semgrep_error": result.semgrep_error,
        "skipped_files": result.skipped_files,
        "finding_count": len(result.findings),
        "findings": [f.model_dump() for f in result.findings],
    }
    print(json.dumps(output, indent=2))

    return 0 if result.overall_status in ("completed", "partial_failure") else 2


if __name__ == "__main__":
    sys.exit(main())
