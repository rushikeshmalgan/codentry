"""Arm C — analysis only: what would combining two arms' independent evidence buy?

Arm C is never a third thing that runs tools. It reads two completed `evaluation.run`
outputs (one per arm) and asks only: how much do they overlap, does one detect more
than the other, and are their detections independent or correlated? [14]'s case for
ensembling static and AI review depends on their errors being *near-independent* —
this module measures that instead of assuming it.

    python -m evaluation.runners.arm_c_union --arm-a-run <dir> [--arm-b-run <dir>] --out <file.json>

**If `--arm-b-run` is omitted** (today: Arm B does not exist), this writes the analysis
*plan* — what would be computed, from which fields, once a second arm's run exists —
and stops. It does not fabricate a second arm's results, and it does not run anything.

With two runs, both must be over the *same case set* (`case_manifest_sha256` must
match) or the comparison is meaningless; this is checked before anything else.

Defect groups are case-local (e.g. a mutation case's `"#0"`), so every group below is
tracked as `(case_id, group)` — never `group` alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluation.metrics.matching import DEFAULT_TOLERANCE, ratio
from evaluation.metrics.stats import mcnemar_exact, wilson_interval

SCHEMA_RESULT = "codentry.eval.arm_c/1"
SCHEMA_PLAN = "codentry.eval.arm_c_plan/1"

PLAN_METRICS = (
    "per-case union/intersection of detected defect groups",
    "overlap matrix per stratum: only-A, only-B, both, neither",
    "recall of the union (Wilson 95% interval), vs. each arm alone",
    "exact McNemar test on the discordant (only-A, only-B) counts per stratum",
    "phi coefficient between the two arms' detection indicators per stratum "
    "(near 0 = near-independent, matching the ensembling argument in [14]; "
    "far from 0 = correlated, and ensembling buys less than it appears to)",
    "unmatched findings per PR for the union (both arms' reported findings pooled; "
    "still not 'false positives' until adjudicated)",
)


class ArmCError(ValueError):
    pass


def _load(run_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    run = json.loads((run_dir / "run.json").read_bytes().decode("utf-8"))
    results = {
        entry["id"]: json.loads(
            (run_dir / entry["id"] / "result.json").read_bytes().decode("utf-8")
        )
        for entry in run["cases"]
    }
    return run, results


def detected_groups(result: dict[str, Any], tolerance: int) -> set[str] | None:
    """Group ids this case's result detected, or None if the case did not complete
    (an incomplete analysis must not silently count as 'found nothing')."""
    if result["status"] != "completed":
        return None
    return set(result["match"][str(tolerance)]["detected_groups"])


def all_groups(result: dict[str, Any]) -> set[str]:
    return {d["group"] for d in result["ground_truth"]}


def phi_coefficient(a: list[bool], b: list[bool]) -> float | None:
    """Pearson correlation of two binary sequences. None if either is constant
    (all-detected or all-missed): correlation is undefined, not zero, then."""
    n = len(a)
    if n == 0 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    mean_a, mean_b = sum(a) / n, sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / n
    var_a = sum((x - mean_a) ** 2 for x in a) / n
    var_b = sum((y - mean_b) ** 2 for y in b) / n
    return cov / (var_a * var_b) ** 0.5


def compare(
    results_a: dict[str, dict[str, Any]],
    results_b: dict[str, dict[str, Any]],
    tolerance: int = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    if set(results_a) != set(results_b):
        raise ArmCError("the two runs do not cover the same cases")
    by_stratum: dict[str, Any] = {}
    strata = {r["stratum"] for r in results_a.values()}
    for stratum in sorted(strata):
        case_ids = sorted(c for c, r in results_a.items() if r["stratum"] == stratum)
        if results_a[case_ids[0]]["ground_truth_status"] != "labeled":
            continue  # recall/overlap are undefined without ground truth
        indicator_a: list[bool] = []
        indicator_b: list[bool] = []
        excluded: list[str] = []
        fp_a = fp_b = 0
        for case_id in case_ids:
            ra, rb = results_a[case_id], results_b[case_id]
            da, db = detected_groups(ra, tolerance), detected_groups(rb, tolerance)
            if da is None or db is None:
                excluded.append(case_id)
                continue
            for group in sorted(all_groups(ra)):
                indicator_a.append(group in da)
                indicator_b.append(group in db)
            fp_a += len(ra["match"][str(tolerance)]["unmatched_finding_indices"])
            fp_b += len(rb["match"][str(tolerance)]["unmatched_finding_indices"])

        n = len(indicator_a)
        union = [a or b for a, b in zip(indicator_a, indicator_b, strict=True)]
        only_a = sum(a and not b for a, b in zip(indicator_a, indicator_b, strict=True))
        only_b = sum(b and not a for a, b in zip(indicator_a, indicator_b, strict=True))
        both = sum(a and b for a, b in zip(indicator_a, indicator_b, strict=True))
        neither = n - only_a - only_b - both
        completed = len(case_ids) - len(excluded)
        by_stratum[stratum] = {
            "cases": len(case_ids),
            "completed_by_both_arms": completed,
            "excluded_incomplete": excluded,
            "defect_groups": n,
            "overlap": {"only_a": only_a, "only_b": only_b, "both": both, "neither": neither},
            "recall_a": _prop(sum(indicator_a), n),
            "recall_b": _prop(sum(indicator_b), n),
            "recall_union": _prop(sum(union), n),
            "mcnemar_p_value": mcnemar_exact(only_a, only_b),
            "phi_coefficient": phi_coefficient(indicator_a, indicator_b),
            "unmatched_per_case": {
                "arm_a": ratio(fp_a, completed) if completed else None,
                "arm_b": ratio(fp_b, completed) if completed else None,
                "union": ratio(fp_a + fp_b, completed) if completed else None,
            },
        }
    return {
        "schema": SCHEMA_RESULT,
        "tolerance": tolerance,
        "strata": by_stratum,
    }


def _prop(successes: int, n: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, n)
    return {"successes": successes, "n": n, "value": ratio(successes, n), "wilson95": [low, high]}


def plan() -> dict[str, Any]:
    return {
        "schema": SCHEMA_PLAN,
        "status": "arm_b_does_not_exist",
        "note": "Arm B is gated (docs/8_DAY_IMPLEMENTATION_PLAN.md Day 5); it was not built "
        "(see docs/AI_ARM_DESIGN_AND_COST.md for why and what it would cost). This is the "
        "analysis Arm C would run the day a second arm's evaluation.run output exists, over "
        "the same case set as Arm A.",
        "would_compute": list(PLAN_METRICS),
        "entry_point": "evaluation.runners.arm_c_union.compare(results_a, results_b)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.runners.arm_c_union")
    parser.add_argument("--arm-a-run", type=Path, required=True)
    parser.add_argument("--arm-b-run", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)

    try:
        if args.arm_b_run is None:
            record = plan()
        else:
            run_a, results_a = _load(args.arm_a_run)
            run_b, results_b = _load(args.arm_b_run)
            if run_a["case_manifest_sha256"] != run_b["case_manifest_sha256"]:
                sha_a = run_a["case_manifest_sha256"][:12]
                sha_b = run_b["case_manifest_sha256"][:12]
                raise ArmCError(f"the two runs are over different case sets ({sha_a}… vs {sha_b}…)")
            record = compare(results_a, results_b, args.tolerance)
    except (ArmCError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    if record["schema"] == SCHEMA_PLAN:
        print("Arm B does not exist: wrote the analysis plan only.")
    else:
        for stratum, s in record["strata"].items():
            print(
                f"{stratum}: recall A={s['recall_a']['value']:.2f} "
                f"B={s['recall_b']['value']:.2f} union={s['recall_union']['value']:.2f}  "
                f"mcnemar p={s['mcnemar_p_value']:.3f}  phi={s['phi_coefficient']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
