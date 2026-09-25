"""Deterministic mutation generator: small, located defects over JS/TS source.

Ground truth here is **known by construction**: a mutant is the original file
with exactly one edit, and the edit's line range is the defect location. That
makes it scalable and cheap, but it is a *proxy* for real faults — mutants can
be trivial or semantically equivalent to the original, and their detectability
does not transfer to real bugs (docs/8_DAY_IMPLEMENTATION_PLAN.md, Day 2).
Equivalence is recorded as "unchecked", never assumed away.

Two strata, always reported separately:

- ``mutant:logic``        eight logic operators (relational/equality flips,
                          &&<->||, negated condition, dropped guard, removed
                          await, off-by-one, changed constant)
- ``mutant:rule-aligned`` one inserted line of a pattern Arm A's rules target
                          (eval, SQL concatenation, hardcoded secret, innerHTML).
                          Kept apart because mixing it with logic mutants would
                          inflate Arm A's recall (construct validity).

Determinism: sites come from evaluation/generators/sites.js in source order;
every choice is made by ``random.Random`` seeded from (global seed, file id,
stratum), so the same inputs always give the same mutants. There is no LLM
anywhere in here, by design.

Only one mutation is applied per mutant; a mutant must parse (TypeScript
syntactic check) and its declared line range must equal the range of an
independent line diff, otherwise it is discarded (and counted).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.case import line_count

GENERATOR_VERSION = 1
GENERATOR_ID = f"codentry-mutate/{GENERATOR_VERSION}"
SITES_JS = Path(__file__).with_name("sites.js")

STRATUM_LOGIC = "mutant:logic"
STRATUM_RULE_ALIGNED = "mutant:rule-aligned"

LOGIC_OPERATORS = (
    "relational-flip",
    "equality-flip",
    "logical-swap",
    "negate-condition",
    "drop-guard",
    "remove-await",
    "off-by-one",
    "constant-change",
)

# One inserted line each. `P` is the enclosing function's first parameter, standing in
# for untrusted input. The forms are chosen so they add no unrelated lint findings
# (no unused or undefined variables): a hit should come from the security rule.
INJECTIONS: dict[str, str] = {
    "eval-usage": "eval({P});",
    "sql-string-concatenation": 'console.log("SELECT * FROM users WHERE id = " + {P});',
    "hardcoded-secret": 'globalThis.apiKey = "sk_live_9f8e7d6c5b4a3210";',
    "innerhtml-assignment": "document.body.innerHTML = {P};",
}
INJECTION_NAMES = tuple(INJECTIONS)

# Oversample candidates so discards (parse errors, ambiguous diffs) don't starve a file.
_CANDIDATE_FACTOR = 3


class GeneratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mutant:
    stratum: str
    operator: str
    index: int  # ordinal within (file, stratum), 1-based
    head_text: str
    start_line: int  # ground-truth range on HEAD lines (inclusive)
    end_line: int
    detail: str


@dataclass
class Generated:
    mutants: list[Mutant]
    discarded: dict[str, int]
    candidates: int


# ---- node helper -----------------------------------------------------------
def run_helper(command: str, items: list[dict[str, str]]) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(SITES_JS)],
        input=json.dumps({"command": command, "items": items}).encode("utf-8"),
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise GeneratorError(f"sites.js failed: {proc.stderr.decode('utf-8', 'replace')[-500:]}")
    return json.loads(proc.stdout.decode("utf-8"))


def typescript_version() -> str:
    return str(run_helper("check", [])["typescript"])


# ---- determinism helpers ---------------------------------------------------
def derive_seed(global_seed: int, file_id: str, stratum: str) -> int:
    """A stable 63-bit seed per (file, stratum); independent of Python's hash seed."""
    digest = hashlib.sha256(f"{GENERATOR_ID}|{global_seed}|{file_id}|{stratum}".encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def _require_simple_text(text: str, filename: str) -> None:
    # sites.js reports UTF-16 offsets and this module slices Python str: they only
    # agree for BMP text. Vendored sources are checked once, here, rather than
    # silently mis-slicing.
    if any(ord(ch) > 0xFFFF for ch in text):
        raise GeneratorError(f"{filename}: contains non-BMP characters")
    if "\r" in text:
        raise GeneratorError(f"{filename}: contains CR; normalize line endings first")


# ---- independent range check ----------------------------------------------
def diff_head_range(base: str, head: str) -> tuple[int, int] | None:
    """Head-side line range of the single changed hunk between two texts, or None if
    there is not exactly one. A pure deletion has no head lines; it is reported as the
    line now sitting at the deletion point (clamped to the file), because that is where
    a reviewer would look for the missing code."""
    matcher = difflib.SequenceMatcher(a=base.split("\n"), b=head.split("\n"), autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if len(changes) != 1:
        return None
    tag, _i1, _i2, j1, j2 = changes[0]
    last = max(line_count(head), 1)
    if tag == "delete":
        line = min(j1 + 1, last)
        return (line, line)
    return (j1 + 1, min(j2, last))


# ---- selection -------------------------------------------------------------
def _draw_order(by_operator: dict[str, list[dict]], rng: random.Random) -> list[dict]:
    """Every site, in the order the RNG draws them: pick an operator uniformly among
    those with sites left, then a site uniformly within it. Operators are therefore
    balanced rather than weighted by how common their syntax is."""
    remaining = {op: list(sites) for op, sites in by_operator.items() if sites}
    order: list[dict] = []
    while remaining:
        op = rng.choice(sorted(remaining))
        order.append(remaining[op].pop(rng.randrange(len(remaining[op]))))
        if not remaining[op]:
            del remaining[op]
    return order


def _accept(
    base: str,
    filename: str,
    candidates: list[tuple[dict, str, tuple[int, int]]],
    count: int,
    stratum: str,
    operator_of,
    detail_of,
) -> Generated:
    items = [
        {"name": str(i), "filename": filename, "text": head}
        for i, (_site, head, _range) in enumerate(candidates)
    ]
    checks = run_helper("check", items)["results"]
    discarded = {"parse_error": 0, "range_mismatch": 0, "duplicate": 0}
    seen = {base}
    mutants: list[Mutant] = []
    for (site, head, declared), check in zip(candidates, checks, strict=True):
        if len(mutants) == count:
            break
        if not check["ok"]:
            discarded["parse_error"] += 1
            continue
        if diff_head_range(base, head) != declared:
            discarded["range_mismatch"] += 1
            continue
        if head in seen:
            discarded["duplicate"] += 1
            continue
        seen.add(head)
        mutants.append(
            Mutant(
                stratum=stratum,
                operator=operator_of(site),
                index=len(mutants) + 1,
                head_text=head,
                start_line=declared[0],
                end_line=declared[1],
                detail=detail_of(site),
            )
        )
    return Generated(mutants, discarded, len(candidates))


def generate_logic(base: str, filename: str, seed: int, count: int) -> Generated:
    _require_simple_text(base, filename)
    sites = run_helper("enumerate", [{"name": "f", "filename": filename, "text": base}])[
        "results"
    ][0]["sites"]
    by_operator: dict[str, list[dict]] = {op: [] for op in LOGIC_OPERATORS}
    for site in sites:
        by_operator[site["operator"]].append(site)

    order = _draw_order(by_operator, random.Random(seed))[: count * _CANDIDATE_FACTOR]
    candidates = []
    for site in order:
        head = base[: site["start"]] + site["replacement"] + base[site["end"] :]
        line = site["line"]
        if site["operator"] == "drop-guard":
            line = min(line, max(line_count(head), 1))
        candidates.append((site, head, (line, line)))
    return _accept(
        base, filename, candidates, count, STRATUM_LOGIC,
        operator_of=lambda s: s["operator"], detail_of=lambda s: s["detail"],
    )


def generate_rule_aligned(base: str, filename: str, seed: int, count: int) -> Generated:
    _require_simple_text(base, filename)
    points = run_helper("enumerate", [{"name": "f", "filename": filename, "text": base}])[
        "results"
    ][0]["points"]
    rng = random.Random(seed)
    order = list(points)
    rng.shuffle(order)
    first_template = rng.randrange(len(INJECTION_NAMES))
    candidates = []
    for i, point in enumerate(order[: count * _CANDIDATE_FACTOR]):
        name = INJECTION_NAMES[(first_template + i) % len(INJECTION_NAMES)]
        line_text = point["indent"] + INJECTIONS[name].replace("{P}", point["param"]) + "\n"
        head = base[: point["offset"]] + line_text + base[point["offset"] :]
        site = {**point, "operator": name}
        candidates.append((site, head, (point["line"], point["line"])))
    return _accept(
        base, filename, candidates, count, STRATUM_RULE_ALIGNED,
        operator_of=lambda s: s["operator"],
        detail_of=lambda s: f"inserted {s['operator']} using parameter {s['param']!r}",
    )
