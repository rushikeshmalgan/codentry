"""Builds labeling items (findings plus code context) from Arm A run results.

    python -m evaluation.labeling.items --results <run-dir> --cases evaluation/cases \\
        --round calibration-01 --count 10 --seed 1 --out evaluation/labeling

Reads the `result.json` files of a run, keeps the findings the arm *reported*
(`change_status == "new"`), samples deterministically, and writes:

    calibration/<round>.items.json   machine-readable items (includes hidden fields)
    calibration/<round>.sheet.md     what the labelers read (no hidden fields)
    labels/<round>.labeler-a.csv     blank label sheets, one per labeler
    labels/<round>.labeler-b.csv

See protocol.md. Hidden fields (identity key, severity, arm, change status) are kept in
the items file for analysis but never shown on the sheet: labelers must not be nudged by
what the tool thought of its own finding.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from pathlib import Path
from typing import Any

CONTEXT_LINES = 8
PER_CASE_CAP = 3
LABELERS = ("a", "b")
CSV_HEADER = ("item_id", "label", "note")


class ItemsError(ValueError):
    pass


def reported_findings(results_dir: Path) -> list[dict[str, Any]]:
    """Every `new` finding across a run, in a stable order, with its case and result path."""
    out: list[dict[str, Any]] = []
    for result_path in sorted(results_dir.glob("*/result.json")):
        result = json.loads(result_path.read_bytes().decode("utf-8"))
        if result.get("status", "completed") != "completed":
            continue  # an incomplete analysis (e.g. a tool timeout) is not a sound source
        for index, finding in enumerate(result["findings"]):
            if finding["change_status"] == "new":
                out.append({"case_id": result["case_id"], "index": index, "finding": finding,
                            "arm": result["arm"]})
    return out


def code_context(cases_dir: Path, case_id: str, finding: dict[str, Any]) -> dict[str, Any]:
    path = cases_dir / case_id / "head" / finding["file_path"]
    if not path.is_file():
        raise ItemsError(f"{case_id}: head file {finding['file_path']!r} not found")
    # a carriage return would show up as garbage on the sheet
    lines = [line.rstrip("\r") for line in path.read_bytes().decode("utf-8").split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    start = max(1, finding["start_line"] - CONTEXT_LINES)
    end = min(len(lines), finding["end_line"] + CONTEXT_LINES)
    return {
        "first_line": start,
        "lines": lines[start - 1 : end],
        "flagged": [finding["start_line"], finding["end_line"]],
    }


def build_items(
    results_dir: Path, cases_dir: Path, round_id: str, count: int, seed: int
) -> list[dict[str, Any]]:
    candidates = reported_findings(results_dir)
    if len(candidates) < count:
        raise ItemsError(f"only {len(candidates)} reported findings available, need {count}")
    rng = random.Random(seed)
    rng.shuffle(candidates)
    chosen: list[dict[str, Any]] = []
    per_case: dict[str, int] = {}
    for c in candidates:
        if len(chosen) == count:
            break
        if per_case.get(c["case_id"], 0) >= PER_CASE_CAP:
            continue
        per_case[c["case_id"]] = per_case.get(c["case_id"], 0) + 1
        chosen.append(c)
    if len(chosen) < count:
        raise ItemsError(f"per-case cap {PER_CASE_CAP} leaves only {len(chosen)} of {count} items")

    items = []
    for position, c in enumerate(chosen, start=1):
        f = c["finding"]
        items.append({
            "item_id": f"{round_id}-{position:02d}",
            "case_id": c["case_id"],
            "tool": f["source"],
            "rule": f["title"],
            "file": f["file_path"],
            "start_line": f["start_line"],
            "end_line": f["end_line"],
            "message": f["description"],
            "context": code_context(cases_dir, c["case_id"], f),
            "hidden": {
                "arm": c["arm"],
                "identity_key": f["identity_key"],
                "severity": f["severity"],
                "change_status": f["change_status"],
                "sampled_with_seed": seed,
            },
        })
    return items


def render_sheet(round_id: str, items: list[dict[str, Any]]) -> str:
    parts = [
        f"# Labeling sheet — {round_id}\n\n"
        "Read `../protocol.md` first. Label each item **independently** in your own file "
        "(`labels/<round>.labeler-<a|b>.csv`): one of `real issue`, `not an issue`, "
        "`unclear`, plus an optional note. Do not reorder items, and do not discuss them with "
        "the other labeler until you have both finished.\n\n"
        "The question: *is this a real problem in the code as written here, something a "
        "reasonable maintainer would want changed?*\n"
    ]
    for item in items:
        ctx = item["context"]
        flagged = range(ctx["flagged"][0], ctx["flagged"][1] + 1)
        width = len(str(ctx["first_line"] + len(ctx["lines"])))
        code = "\n".join(
            f"{'>' if n in flagged else ' '} {n:>{width}} | {text}"
            for n, text in enumerate(ctx["lines"], start=ctx["first_line"])
        )
        where = (f"line {item['start_line']}" if item["start_line"] == item["end_line"]
                 else f"lines {item['start_line']}-{item['end_line']}")
        parts.append(
            f"\n---\n\n## {item['item_id']}\n\n"
            f"- **Project / case:** `{item['case_id']}`\n"
            f"- **File:** `{item['file']}`, {where}\n"
            f"- **Tool:** {item['tool']}  ·  **Rule:** `{item['rule']}`\n"
            f"- **Message:** {item['message']}\n\n"
            f"```text\n{code}\n```\n"
        )
    return "".join(parts)


def blank_label_csv(items: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for item in items:
        writer.writerow([item["item_id"], "", ""])
    return buffer.getvalue()


def write_round(out: Path, round_id: str, items: list[dict[str, Any]]) -> list[Path]:
    kind = out / "calibration"
    written = []
    files = {
        kind / f"{round_id}.items.json": (json.dumps(items, indent=2, sort_keys=True) + "\n"),
        kind / f"{round_id}.sheet.md": render_sheet(round_id, items),
    }
    for who in LABELERS:
        files[out / "labels" / f"{round_id}.labeler-{who}.csv"] = blank_label_csv(items)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.labeling.items")
    parser.add_argument("--results", type=Path, required=True, help="an evaluation.run output dir")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--round", required=True, help="e.g. calibration-01")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        items = build_items(args.results, args.cases, args.round, args.count, args.seed)
        for path in write_round(args.out, args.round, items):
            print(path)
    except (ItemsError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
