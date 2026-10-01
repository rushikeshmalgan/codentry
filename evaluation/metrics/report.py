"""Turns one evaluation run into a report: Markdown for people, JSON for tools.

    python -m evaluation.metrics.report --run <run-dir> \\
        [--identity-stability <file.json>] --out-dir evaluation/reports --name 2026-09-27-arm-a

The report is a **pure function of files already on disk** (`run.json`, every
`<case>/result.json`, and optionally `timing.json` and an identity-stability
JSON): same inputs, same bytes. It contains no timestamp and no absolute path;
the date, if any, lives only in the file name the caller chooses.

What it will not do, by design:

- no single overall score, and strata are never pooled (mutation logic edits,
  rule-aligned injections, real bugs and noise-measurement pull requests answer
  different questions);
- no precision and no "false positives per pull request" until people have
  adjudicated findings (protocol: evaluation/labeling/protocol.md). Findings that
  match no known defect are reported as *unmatched*, never as false positives;
- every proportion is printed with its counts and a 95% Wilson interval;
- hand-made fixture cases are listed as excluded, not measured.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evaluation.metrics.matching import DEFAULT_TOLERANCE, TOLERANCES, ratio
from evaluation.metrics.stats import bootstrap_interval, wilson_interval

REPORT_SCHEMA = "codentry.eval.report/1"
BOOTSTRAP_SEED = 20260927
BOOTSTRAP_RESAMPLES = 10_000

LIMITATIONS = (
    "**Arm A is a small hand-written ruleset.** It is ESLint with Codentry's baseline "
    "config plus six Semgrep rules; results say nothing about Semgrep's registry rules or "
    "about static analysis in general.",
    "**Location-only matching.** A finding \"hits\" a defect if it overlaps the defect's "
    "lines (widened by k). It cannot tell whether the finding describes the defect, so a "
    "hit can be a coincidence, and a finding that points at the defect from elsewhere is "
    "scored unmatched. Recall is shown for k = 0, 2 and 5; read the k = 0 row too.",
    "**Mutants are a proxy for real faults.** Equivalence is unchecked, so some mutants may "
    "not change behavior; mutation logic edits are mostly not the kind of defect a lint "
    "rule can see.",
    "**The rule-aligned stratum is favorable to Arm A by construction:** each injected line "
    "is a pattern one of Arm A's six rules targets. It is reported apart and must never be "
    "pooled with the others.",
    "**Real-defect cases are reversed fixes, not natural pull requests,** taken from a "
    "public benchmark; some have no recorded failing test and rest on the dataset's manual "
    "validation alone (evaluation/datasets/bugsjs.json says which).",
    "**Contamination.** Every source is a public project a language model may have seen; "
    "this affects only future AI arms, but it constrains what these cases can show.",
    "**Small, clustered samples.** Cases from the same file or project are not independent, "
    "so the Wilson intervals (which assume independent trials) are narrower than the true "
    "uncertainty.",
    "**Noise pull requests are selected mechanically** from repository history "
    "(squash-merge commits), including trivial ones; they measure volume, not correctness.",
    "**No adjudication has been done.** Precision and false positives per pull request need "
    "two independent human labelers; that step is open and is not estimated here.",
    "**Tool timeouts are recorded, not hidden.** A case whose analysis did not complete is "
    "excluded from the metrics and listed; it is never scored as a clean run.",
)


# ---- small numeric helpers ---------------------------------------------------------
def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _prop(successes: int, n: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "value": ratio(successes, n),
        "wilson95": [low, high] if n else None,
    }


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile of an already sorted, non-empty sequence."""
    rank = max(1, math.ceil(q * len(sorted_values)))
    return sorted_values[rank - 1]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _fmt_prop(p: dict[str, Any]) -> str:
    if not p["n"]:
        return "n/a (no cases)"
    low, high = p["wilson95"]
    return f"{p['successes']}/{p['n']} = {_pct(p['value'])} (95% CI {_pct(low)}–{_pct(high)})"


# ---- reading a run -----------------------------------------------------------------
def load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float] | None]:
    run = json.loads((run_dir / "run.json").read_bytes().decode("utf-8"))
    results = [
        json.loads((run_dir / entry["id"] / "result.json").read_bytes().decode("utf-8"))
        for entry in run["cases"]
    ]
    timing_path = run_dir / "timing.json"
    timing = (
        json.loads(timing_path.read_bytes().decode("utf-8"))["seconds_per_case"]
        if timing_path.exists()
        else None
    )
    return run, results, timing


def _stratum_kind(name: str, results: list[dict[str, Any]]) -> str:
    if name.startswith("fixture:"):
        return "fixture"
    return "labeled" if all(r["ground_truth_status"] == "labeled" for r in results) else "unlabeled"


# ---- aggregation -------------------------------------------------------------------
def _aggregate_stratum(
    name: str, results: list[dict[str, Any]], timing: dict[str, float] | None
) -> dict[str, Any]:
    kind = _stratum_kind(name, results)
    completed = [r for r in results if r["status"] == "completed"]
    excluded = sorted(r["case_id"] for r in results if r["status"] != "completed")
    out: dict[str, Any] = {
        "kind": kind,
        "cases": len(results),
        "case_ids": sorted(r["case_id"] for r in results),
        "completed": len(completed),
        "excluded_incomplete": excluded,
    }
    if kind == "fixture" or not completed:
        return out

    k_default = str(DEFAULT_TOLERANCE)
    counts = [r["counts"] for r in completed]
    reported = [c["reported"] for c in counts]
    changed = sum(c["changed_lines"] for c in counts)
    out["findings"] = {
        "new": sum(c["new"] for c in counts),
        "existing": sum(c["existing"] for c in counts),
        "fixed": sum(c["fixed"] for c in counts),
        "unclassified": sum(c["unclassified"] for c in counts),
    }
    out["reported"] = {
        "total": sum(reported),
        "mean_per_case": _mean(reported),
        "mean_per_case_bootstrap95": list(
            bootstrap_interval(
                [float(v) for v in reported], _mean, BOOTSTRAP_SEED, 0.95, BOOTSTRAP_RESAMPLES
            )
        ),
        "median_per_case": _quantile(sorted(reported), 0.5),
        "max_per_case": max(reported),
        "per_100_changed_lines": (100 * sum(reported) / changed) if changed else None,
        "changed_lines": changed,
    }
    out["duplicates"] = _prop(sum(c["reported_duplicates"] for c in counts), sum(reported))
    out["existing_share"] = _prop(
        out["findings"]["existing"], out["findings"]["existing"] + out["findings"]["new"]
    )

    if kind == "labeled":
        recall = {}
        for k in TOLERANCES:
            m = [r["match"][str(k)] for r in completed]
            recall[str(k)] = _prop(sum(x["detected"] for x in m), sum(x["defects"] for x in m))
        out["recall"] = recall
        m2 = [r["match"][k_default] for r in completed]
        matched = sum(len(x["matched_finding_indices"]) for x in m2)
        out["matched_findings"] = matched
        out["unmatched_findings"] = sum(len(x["unmatched_finding_indices"]) for x in m2)
        out["location_accuracy"] = _prop(sum(x["exactly_located"] for x in m2), matched)
        out["cases_with_a_detected_defect"] = _prop(
            sum(1 for x in m2 if x["detected"] > 0), len(m2)
        )

    if timing is not None:
        seconds = sorted(timing[r["case_id"]] for r in completed if r["case_id"] in timing)
        if seconds:
            out["latency_seconds"] = {
                "n": len(seconds),
                "median": _quantile(seconds, 0.5),
                "p90": _quantile(seconds, 0.9),
                "max": seconds[-1],
            }
    return out


def aggregate(run_dir: Path, identity_stability: Path | None = None) -> dict[str, Any]:
    run, results, timing = load_run(run_dir)
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_stratum.setdefault(r["stratum"], []).append(r)
    strata = {name: _aggregate_stratum(name, rs, timing) for name, rs in sorted(by_stratum.items())}
    stability = (
        json.loads(identity_stability.read_bytes().decode("utf-8")) if identity_stability else None
    )
    return {
        "schema": REPORT_SCHEMA,
        "arm": run["arm"],
        "arm_label": run["arm_label"],
        "reported_policy": run["reported_policy"],
        "default_tolerance": run["default_tolerance"],
        "provenance": {
            "git": run["git"],
            "case_manifest_sha256": run["case_manifest_sha256"],
            "results_sha256": run["results_sha256"],
            "tools": run["tools"],
            "case_count": run["case_count"],
            "status_counts": run["status_counts"],
            "latency_measured": timing is not None,
        },
        "strata": strata,
        "identity_stability": stability,
        "adjudication": {
            "status": "not_done",
            "note": "They need two independent human labelers "
            "(evaluation/labeling/protocol.md); that step is open.",
        },
        "limitations": list(LIMITATIONS),
    }


# ---- rendering ---------------------------------------------------------------------
_TITLES = {
    "mutant:logic": "Mutation-seeded logic defects (`mutant:logic`)",
    "mutant:rule-aligned": "Rule-aligned injections (`mutant:rule-aligned`) — favorable to Arm A by construction",
    "real:bugsjs": "Real defects, fixes reversed (`real:bugsjs`)",
    "noise:pr": "Merged pull requests, no defect labels (`noise:pr`)",
}


def _render_stratum(name: str, s: dict[str, Any], default_k: int) -> list[str]:
    lines = [f"### {_TITLES.get(name, f'`{name}`')}", ""]
    lines.append(
        f"{s['cases']} cases; {s['completed']} completed"
        + (f"; **excluded (analysis incomplete): {', '.join(s['excluded_incomplete'])}**"
           if s["excluded_incomplete"] else "")
        + ". Metrics use completed cases only."
    )
    lines.append("")
    if s["completed"] == 0:
        return lines + ["No completed cases.", ""]
    if s["kind"] == "labeled":
        lines += ["| Recall of known defects | detected / defects |", "|---|---|"]
        for k in TOLERANCES:
            tag = " (headline)" if k == default_k else ""
            lines.append(f"| k = {k}{tag} | {_fmt_prop(s['recall'][str(k)])} |")
        lines += [
            "",
            f"- Cases in which at least one defect was detected (k = {default_k}): "
            f"{_fmt_prop(s['cases_with_a_detected_defect'])}",
            f"- Location accuracy of matched findings (share that overlap the defect exactly): "
            f"{_fmt_prop(s['location_accuracy'])}",
            f"- Findings matched to a known defect: {s['matched_findings']}; **unmatched: "
            f"{s['unmatched_findings']}** (not adjudicated — not false positives)",
        ]
    rep = s["reported"]
    low, high = rep["mean_per_case_bootstrap95"]
    lines += [
        f"- Reported (`new`) findings: {rep['total']} in {s['completed']} cases; mean "
        f"{rep['mean_per_case']:.2f} per case (95% bootstrap CI {low:.2f}–{high:.2f}), median "
        f"{rep['median_per_case']:g}, max {rep['max_per_case']}",
        "- Reported findings per 100 changed lines: "
        + ("n/a" if rep["per_100_changed_lines"] is None else f"{rep['per_100_changed_lines']:.2f}")
        + f" ({rep['changed_lines']} changed lines)",
        f"- Pre-existing share of findings on touched files (`existing` / (`new` + `existing`)): "
        f"{_fmt_prop(s['existing_share'])} — findings a naive whole-file review would have blamed on the change",
        f"- Duplicate rate among reported findings: {_fmt_prop(s['duplicates'])}",
    ]
    if "latency_seconds" in s:
        lat = s["latency_seconds"]
        lines.append(
            f"- Analysis wall time per case (this machine): median {lat['median']:.1f} s, "
            f"90th percentile {lat['p90']:.1f} s, max {lat['max']:.1f} s (n = {lat['n']})"
        )
    return lines + [""]


def _render_stability(stab: dict[str, Any]) -> list[str]:
    lines = [
        "## Finding identity under changes that are not edits to the finding",
        "",
        f"Real files from the real-defect and pull-request cases that had at least one finding "
        f"({stab['files_with_findings']} of {stab['files_examined']} files, "
        f"{stab['findings_before']} findings) were re-analyzed after two transformations. A "
        "finding is *stable* if its `identity_key` is still present afterwards.",
        "",
        "| Transformation | stable / findings | vanished | appeared |",
        "|---|---|---|---|",
    ]
    for name, row in sorted(stab["transforms"].items()):
        p = _prop(row["stable"], row["before"])
        lines.append(f"| `{name}` | {_fmt_prop(p)} | {row['vanished']} | {row['appeared']} |")
    return lines + [
        "",
        "Line shift = three blank lines inserted at the top; whitespace = two trailing spaces on "
        "every non-blank line. Neither ruleset nor transformation includes anything that would "
        "make a whitespace-sensitive rule fire, so a stable result here is expected, not surprising; "
        "it shows the identity design survives these realistic incidental edits, not that it survives "
        "every refactor (renaming an identifier in a flagged line looks like a fixed + new finding).",
        "",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    prov = report["provenance"]
    k = report["default_tolerance"]
    git = prov["git"]
    lines = [
        f"# Arm A evaluation report — {report['arm_label']}",
        "",
        "> **Read this first.** These are the first numbers this project has produced, from small "
        "public-code corpora, with a small hand-written ruleset. Strata answer different questions "
        "and are never combined; there is no overall score. Precision and false positives per pull "
        "request are **not estimated** (see *Not measured*). Every proportion shows its counts and "
        "a 95% Wilson interval.",
        "",
        "## Provenance",
        "",
        f"- Arm: {report['arm_label']} — reported findings are those with `{report['reported_policy']}`",
        f"- Cases: {prov['case_count']} ({', '.join(f'{v} {s}' for s, v in sorted(prov['status_counts'].items()))})",
        f"- Case set SHA-256: `{prov['case_manifest_sha256']}`",
        f"- Results SHA-256: `{prov['results_sha256']}`",
        f"- Code commit: `{git['commit']}`"
        + (" — **the working tree had uncommitted changes when this ran**" if git.get("dirty") else ""),
        "- Tools: " + ", ".join(
            f"{name} {prov['tools'][name]}"
            for name in ("eslint_version", "semgrep_version", "node_version", "python_version")
            if prov["tools"].get(name)
        ) + f"; ruleset SHA-256 `{prov['tools']['ruleset_sha256'][:16]}…`",
        f"- Default match tolerance k = {k} lines (sensitivity at k = "
        + ", ".join(str(t) for t in TOLERANCES if t != k) + " shown alongside)",
        "",
        "## Results by stratum",
        "",
    ]
    order = [n for n in ("mutant:logic", "mutant:rule-aligned", "real:bugsjs", "noise:pr")
             if n in report["strata"]]
    order += [n for n in report["strata"] if n not in order and report["strata"][n]["kind"] != "fixture"]
    for name in order:
        lines += _render_stratum(name, report["strata"][name], k)
    fixtures = {n: s for n, s in report["strata"].items() if s["kind"] == "fixture"}
    if fixtures:
        ids = ", ".join(f"`{i}`" for s in fixtures.values() for i in s["case_ids"])
        lines += [
            "### Excluded: harness self-test fixtures",
            "",
            f"{ids} test the harness, are hand-made, and are not evidence. They are not measured here.",
            "",
        ]
    if report["identity_stability"]:
        lines += _render_stability(report["identity_stability"])
    lines += [
        "## Not measured",
        "",
        f"- **Precision and false positives per pull request are not estimated.** "
        f"{report['adjudication']['note']} "
        "Until then, \"unmatched\" above is a count of findings that hit no known defect — some may "
        "be real problems the ground truth does not list, and some hits may be coincidences.",
        "- Anything about AI review: no AI arm exists.",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"{i}. {text}" for i, text in enumerate(report["limitations"], start=1)]
    lines += ["", "## Case lists (every number above is computed from exactly these cases)", ""]
    for name, s in report["strata"].items():
        lines.append(f"- `{name}` ({s['cases']}): " + ", ".join(f"`{c}`" for c in s["case_ids"]))
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.metrics.report")
    parser.add_argument("--run", type=Path, required=True, help="an evaluation.run output directory")
    parser.add_argument("--identity-stability", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--name", required=True, help="file stem, e.g. 2026-09-27-arm-a")
    args = parser.parse_args(argv)
    try:
        report = aggregate(args.run, args.identity_stability)
    except (OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{args.name}.md").write_bytes(render_markdown(report).encode("utf-8"))
    (args.out_dir / f"{args.name}.json").write_bytes(render_json(report).encode("utf-8"))
    print(f"wrote {args.out_dir / (args.name + '.md')} and .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
