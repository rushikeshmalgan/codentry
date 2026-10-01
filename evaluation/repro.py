"""Reproducibility check: does a recorded run, and its report, still reproduce?

    python -m evaluation.repro --run <run-dir> --cases evaluation/cases \\
        [--report-md FILE --report-json FILE [--identity-stability FILE]] [--no-rerun]

Two independent checks; the exit code is 0 only if every requested check passes.

1. **Results** (skipped with ``--no-rerun``): re-run Arm A on the same cases into a
   temporary directory and compare with the recorded ``run.json`` — the case-set
   hash, the ruleset and tool versions, and ``results_sha256``. A difference in any
   input (a case file, the ruleset, a tool version) shows up here, naming the cases
   whose results changed.
2. **Report**: regenerate the Markdown and JSON report from the *recorded* run files
   and compare bytes with the stored report. The report is a pure function of those
   files, so a difference means the stored report was edited by hand or the report
   code changed.

Latency is deliberately not compared: wall-clock time differs between runs by
nature (it lives in ``timing.json``, outside every hash).

Exit codes: 0 all checks passed; 1 a check failed (the reasons are printed);
2 the check could not be run (missing files, unreadable case).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from evaluation.case import CaseError
from evaluation.metrics import report
from evaluation.run import run

_TOOL_KEYS = ("eslint_version", "semgrep_version", "ruleset_sha256", "baseline_config_sha256")


def compare_runs(recorded: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Human-readable differences between two run.json records (empty = reproduces)."""
    problems: list[str] = []
    if recorded["case_manifest_sha256"] != fresh["case_manifest_sha256"]:
        problems.append("the case files differ from the recorded run (case-set hash changed)")
    for key in _TOOL_KEYS:
        if recorded["tools"].get(key) != fresh["tools"].get(key):
            problems.append(
                f"{key} differs: recorded {recorded['tools'].get(key)!r}, "
                f"now {fresh['tools'].get(key)!r}"
            )
    old = {c["id"]: c["result_sha256"] for c in recorded["cases"]}
    new = {c["id"]: c["result_sha256"] for c in fresh["cases"]}
    for case_id in sorted(set(old) | set(new)):
        if case_id not in new:
            problems.append(f"case {case_id} is no longer present")
        elif case_id not in old:
            problems.append(f"case {case_id} was not in the recorded run")
        elif old[case_id] != new[case_id]:
            problems.append(f"case {case_id}: result changed")
    if recorded["results_sha256"] != fresh["results_sha256"] and not problems:
        problems.append("results_sha256 differs")
    return problems


def check_results(run_dir: Path, cases_dir: Path) -> list[str]:
    recorded = json.loads((run_dir / "run.json").read_bytes().decode("utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        fresh = run(cases_dir, Path(tmp) / "rerun", recorded["seed"])
    return compare_runs(recorded, fresh)


def check_report(
    run_dir: Path, md: Path, json_path: Path, identity_stability: Path | None
) -> list[str]:
    regenerated = report.aggregate(run_dir, identity_stability)
    problems = []
    if report.render_markdown(regenerated).encode("utf-8") != md.read_bytes():
        problems.append(f"{md.name}: does not match the report regenerated from the run files")
    if report.render_json(regenerated).encode("utf-8") != json_path.read_bytes():
        problems.append(
            f"{json_path.name}: does not match the report regenerated from the run files"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.repro")
    parser.add_argument(
        "--run", type=Path, required=True, help="a recorded evaluation.run directory"
    )
    parser.add_argument(
        "--cases", type=Path, help="the cases directory (required unless --no-rerun)"
    )
    parser.add_argument("--no-rerun", action="store_true", help="skip re-running Arm A")
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--identity-stability", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.no_rerun and args.cases is None:
        parser.error("--cases is required unless --no-rerun")
    if bool(args.report_md) != bool(args.report_json):
        parser.error("--report-md and --report-json go together")
    if args.no_rerun and not args.report_md:
        parser.error("nothing to check: give a report, or drop --no-rerun")

    checks: list[tuple[str, list[str]]] = []
    try:
        if not args.no_rerun:
            checks.append(("results", check_results(args.run, args.cases)))
        if args.report_md:
            problems = check_report(
                args.run, args.report_md, args.report_json, args.identity_stability
            )
            checks.append(("report", problems))
    except (OSError, KeyError, ValueError, CaseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failed = False
    for name, problems in checks:
        if problems:
            failed = True
            print(f"FAIL {name}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
