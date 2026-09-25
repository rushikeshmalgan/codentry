"""Reading and validating label files, and measuring how much two labelers agree.

    python -m evaluation.labeling.agreement --items <round>.items.json --a <a.csv> --b <b.csv>

Validation comes first and is strict: a label file must have exactly the header
`item_id,label,note`, one row for every item and no others, and only the three legal
labels. Invalid input is refused with a message naming the problem; nothing is computed
from a half-filled sheet (a blank label silently counted as a disagreement, or dropped,
would change the result).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from evaluation.metrics.stats import cohens_kappa

LABELS = ("real issue", "not an issue", "unclear")
HEADER = ["item_id", "label", "note"]


class LabelError(ValueError):
    """A label file or item file is invalid."""


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float | None
    kappa: float | None
    # `unclear` is an escape hatch whose meaning differs between people, so kappa is also
    # reported with it merged into `not an issue`
    kappa_unclear_as_not_an_issue: float | None
    confusion: dict[tuple[str, str], int]  # (labeler a's label, labeler b's label) -> count
    disagreements: tuple[str, ...]  # item ids


def read_item_ids(items_path: Path) -> list[str]:
    items = json.loads(items_path.read_bytes().decode("utf-8"))
    ids = [item["item_id"] for item in items]
    if len(set(ids)) != len(ids):
        raise LabelError(f"{items_path.name}: duplicate item ids")
    return ids


def read_labels(path: Path, item_ids: list[str]) -> dict[str, tuple[str, str]]:
    """{item_id: (label, note)}; raises LabelError for anything that is not a complete,
    legal label sheet for exactly these items."""
    text = path.read_bytes().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [c.strip() for c in rows[0]] != HEADER:
        raise LabelError(f"{path.name}: header must be exactly {','.join(HEADER)}")
    labels: dict[str, tuple[str, str]] = {}
    for number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # blank line
        if len(row) != 3:
            raise LabelError(f"{path.name}: line {number} has {len(row)} columns, expected 3")
        item_id, label, note = row[0].strip(), row[1].strip(), row[2]
        if item_id in labels:
            raise LabelError(f"{path.name}: {item_id} appears more than once")
        if label not in LABELS:
            shown = label or "(blank)"
            raise LabelError(
                f"{path.name}: {item_id} has label {shown!r}; use one of: " + ", ".join(LABELS)
            )
        labels[item_id] = (label, note)
    missing = [i for i in item_ids if i not in labels]
    extra = sorted(set(labels) - set(item_ids))
    if missing:
        raise LabelError(f"{path.name}: missing labels for {', '.join(missing)}")
    if extra:
        raise LabelError(f"{path.name}: unknown items {', '.join(extra)}")
    return labels


def compare(
    labels_a: dict[str, tuple[str, str]], labels_b: dict[str, tuple[str, str]], item_ids: list[str]
) -> Agreement:
    a = [labels_a[i][0] for i in item_ids]
    b = [labels_b[i][0] for i in item_ids]
    merged = {"unclear": "not an issue"}
    confusion: dict[tuple[str, str], int] = {}
    for pair in zip(a, b, strict=True):
        confusion[pair] = confusion.get(pair, 0) + 1
    n = len(item_ids)
    return Agreement(
        n=n,
        observed=(sum(x == y for x, y in zip(a, b, strict=True)) / n) if n else None,
        kappa=cohens_kappa(a, b),
        kappa_unclear_as_not_an_issue=cohens_kappa(
            [merged.get(x, x) for x in a], [merged.get(y, y) for y in b]
        ),
        confusion=dict(sorted(confusion.items())),
        disagreements=tuple(i for i, x, y in zip(item_ids, a, b, strict=True) if x != y),
    )


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.labeling.agreement")
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--a", type=Path, required=True, help="labeler A's csv")
    parser.add_argument("--b", type=Path, required=True, help="labeler B's csv")
    args = parser.parse_args(argv)
    try:
        ids = read_item_ids(args.items)
        result = compare(read_labels(args.a, ids), read_labels(args.b, ids), ids)
    except (LabelError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"items: {result.n}   raw agreement: {_fmt(result.observed)}")
    print(f"Cohen's kappa (3 labels): {_fmt(result.kappa)}")
    print(f"Cohen's kappa (unclear merged into 'not an issue'): "
          f"{_fmt(result.kappa_unclear_as_not_an_issue)}")
    print("confusion (labeler A, labeler B): count")
    for (x, y), count in result.confusion.items():
        print(f"  ({x}, {y}): {count}")
    print("disagreements to discuss:", ", ".join(result.disagreements) or "none")
    if result.n < 30:
        print("note: with so few items the kappa interval is very wide; this is practice, "
              "not a reported figure", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
