"""Command-line entry point for the evaluation harness.

    python -m evaluation.run --arm A --cases evaluation/cases --out evaluation/reports/<run-id>

(from the repository root, with PYTHONPATH=services/ai-review so `analysis` imports)

Writes, under --out:

    <case-id>/result.json   what the arm found + how it scores. Deterministic:
                            byte-identical across runs on one machine (no
                            timestamps, durations or absolute paths).
    run.json                everything needed to reproduce the run: tool
                            versions, ruleset and baseline-config SHA-256, case
                            manifest hash, seed, git commit, and a hash of all
                            results. Also deterministic, by design.

Only Arm A exists. Arms B/C (AI) are deliberately not implemented; asking for
them is an error, not a silent fallback.

Nothing here calls GitHub, a database, or any network service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from evaluation.case import CaseError, discover_case_dirs, load_case, manifest_sha256
from evaluation.metrics.matching import DEFAULT_TOLERANCE, TOLERANCES
from evaluation.record import build_result
from evaluation.runners.arm_a_static import ARM_ID, REPORTED_POLICY, arm_label, run_arm_a

RUN_SCHEMA = "codentry.eval.run/2"
REPO_ROOT = Path(__file__).resolve().parent.parent


def dumps(obj: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, fixed indent, ASCII, LF, trailing newline."""
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_capture(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _node_version() -> str | None:
    node = shutil.which("node")  # the same lookup the ESLint runner uses
    return _run_capture([node, "--version"]) if node else None


def _repo_relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None


def git_state(exclude: list[Path]) -> dict[str, Any]:
    """Commit and whether the working tree differs from it (untracked files
    included). Output directories are excluded so writing a report does not make
    the *next* run look dirty."""
    commit = _run_capture(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
    if commit is None:
        return {"commit": None, "dirty": None}
    pathspecs = ["."]
    for path in exclude:
        relative = _repo_relative(path)
        if relative:
            pathspecs.append(f":(exclude){relative}")
    status = _run_capture(["git", "status", "--porcelain", "--", *pathspecs], cwd=REPO_ROOT)
    return {"commit": commit, "dirty": None if status is None else bool(status)}


def run(cases_dir: Path, out_dir: Path, seed: int, overwrite: bool = False) -> dict[str, Any]:
    case_dirs = discover_case_dirs(cases_dir)
    if not case_dirs:
        raise CaseError(f"no cases found under {cases_dir} (looking for */case.json)")
    if (out_dir / "run.json").exists() and not overwrite:
        raise CaseError(f"{out_dir} already holds a run; choose a new --out or pass --overwrite")

    # Load (and validate) every case before analyzing any: a malformed case
    # aborts the run instead of silently shrinking the denominator.
    cases = [load_case(d) for d in case_dirs]
    git = git_state([out_dir, REPO_ROOT / "evaluation" / "reports"])

    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    tool_meta: dict[str, Any] = {}
    for case in cases:
        result = run_arm_a(case.inputs)
        record = build_result(case, result)
        payload = dumps(record)
        (out_dir / case.id).mkdir(parents=True, exist_ok=True)
        (out_dir / case.id / "result.json").write_bytes(payload)
        if not tool_meta:
            tool_meta = {
                key: result.analysis_meta.get("head", {}).get(key)
                for key in (
                    "eslint_version",
                    "semgrep_version",
                    "ruleset_sha256",
                    "baseline_config_sha256",
                    "identity_version",
                )
            }
        entries.append(
            {
                "id": case.id,
                "stratum": case.stratum,
                "ground_truth_status": case.ground_truth_status,
                "status": record["status"],
                "result_sha256": _sha256(payload),
                "reported": record["counts"]["reported"],
                "ground_truth_defects": record["counts"]["ground_truth_defects"],
                "detected_at_default_tolerance": (
                    record["match"][str(DEFAULT_TOLERANCE)]["detected"]
                ),
            }
        )

    status_counts: dict[str, int] = {}
    for e in entries:
        status_counts[e["status"]] = status_counts.get(e["status"], 0) + 1

    run_record = {
        "schema": RUN_SCHEMA,
        "arm": ARM_ID,
        "arm_label": arm_label(tool_meta.get("semgrep_version")),
        "reported_policy": REPORTED_POLICY,
        "tolerances": list(TOLERANCES),
        "default_tolerance": DEFAULT_TOLERANCE,
        # Arm A is fully deterministic and consumes no randomness; the seed is recorded
        # so runs of arms/statistics that do (bootstrap, later arms) share one field.
        "seed": seed,
        "tools": {
            **tool_meta,
            "node_version": _node_version(),
            "python_version": platform.python_version(),
            "platform": sys.platform,
        },
        "git": git,
        "cases_dir": _repo_relative(cases_dir) or cases_dir.name,
        "case_manifest_sha256": manifest_sha256(case_dirs),
        "case_count": len(entries),
        "status_counts": status_counts,
        "cases": entries,
        # One hash over every case's result bytes: two runs are identical iff this matches.
        "results_sha256": _sha256(
            dumps([[e["id"], e["result_sha256"]] for e in entries])
        ),
    }
    (out_dir / "run.json").write_bytes(dumps(run_record))
    return run_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.run", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--arm", required=True, choices=[ARM_ID], help="A = static analysis (only arm implemented)"
    )
    parser.add_argument("--cases", required=True, type=Path, help="directory of case directories")
    parser.add_argument("--out", required=True, type=Path, help="output directory (created)")
    parser.add_argument("--seed", type=int, default=0, help="recorded in run.json (default 0)")
    parser.add_argument(
        "--overwrite", action="store_true", help="allow --out to already hold a run"
    )
    args = parser.parse_args(argv)

    try:
        record = run(args.cases, args.out, args.seed, args.overwrite)
    except CaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(record["arm_label"])
    print(f"cases: {record['case_count']}  statuses: {record['status_counts']}")
    for e in record["cases"]:
        print(
            f"  {e['id']:<40} {e['status']:<10} reported={e['reported']:<3} "
            f"defects detected={e['detected_at_default_tolerance']}/{e['ground_truth_defects']} "
            f"(k={DEFAULT_TOLERANCE})"
        )
    print(f"results_sha256: {record['results_sha256']}")
    if any(status != "completed" for status in record["status_counts"]):
        print(
            "warning: some cases did not complete; see status in each result.json",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
