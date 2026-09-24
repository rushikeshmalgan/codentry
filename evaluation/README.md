# evaluation/

The offline evaluation harness. **Status: Day 1 core only** — a deterministic
pipeline from a case directory, through Arm A (static analysis), to a metrics
record. There is **no AI arm, no real dataset, no aggregate report, and no
measured result.** The two cases in `cases/` are hand-made harness fixtures
(stratum `fixture:*`); running over them tests the harness, it is not evidence.

Research question, arms, ground-truth rules and metrics:
[`../docs/research-design.md`](../docs/research-design.md). What comes next:
[`../docs/8_DAY_IMPLEMENTATION_PLAN.md`](../docs/8_DAY_IMPLEMENTATION_PLAN.md).

## Run it

From the repository root. You need the Python environment of `services/ai-review`
(`pip install -r requirements-dev.txt`), Node, and the ESLint baseline install
(`npm install` in `services/ai-review/analysis/eslint-baseline`).

```bash
# bash
PYTHONPATH=services/ai-review python -m evaluation.run --arm A \
    --cases evaluation/cases --out evaluation/reports/<run-id>
PYTHONPATH=services/ai-review python -m pytest evaluation/tests
ruff check evaluation
```

```powershell
# PowerShell
$env:PYTHONPATH = "services/ai-review"
python -m evaluation.run --arm A --cases evaluation/cases --out evaluation/reports/<run-id>
```

`--arm B`, `C`, `D` are refused: those arms do not exist. `--out` must not
already hold a run unless you pass `--overwrite`. A malformed case aborts the
whole run (a silently skipped case would change every denominator).

Expect roughly 15–20 seconds per case on a developer laptop: each case starts
Semgrep twice (base and head). The harness tests take a few minutes because they
run the real tools, including two full CLI runs that must match byte for byte.

## Layout

```
evaluation/
  schema/case.schema.json   the case format (JSON Schema, draft 2020-12)
  case.py                   load + validate a case; CaseInputs (what an arm may see) vs ground truth
  cases/<case-id>/          case.json, base/…, head/…   (bytes pinned by cases/.gitattributes)
  runners/arm_a_static.py   Arm A: runs analysis.snapshot_analysis on a case (the production code path)
  record.py                 per-case result record: findings + how they score
  metrics/matching.py       finding ↔ defect matching, ±k tolerance, duplicates
  metrics/stats.py          Wilson interval, exact McNemar, seeded bootstrap
  run.py                    the CLI
  tests/                    harness tests
  reports/                  (created by you) run outputs; never hand-edited
```

## What a run writes

- `<out>/<case-id>/result.json` — the arm's findings (every `new` / `existing` /
  `fixed` / unclassified finding), and per-tolerance scoring for k ∈ {0, 2, 5}.
- `<out>/run.json` — tool versions (ESLint, Semgrep, Node, Python), ruleset and
  baseline-config SHA-256, case-manifest hash, seed, git commit and whether the
  working tree was dirty, per-case result hashes, and `results_sha256` over all
  results.

Both are canonical JSON with **no timestamps, durations or absolute paths**, so
two runs on one machine are byte-identical and `results_sha256` is the one number
to compare. (Verified: the test suite runs the CLI twice as a subprocess and
compares every byte.) Latency, when it is measured, will go in a separate file.

## Definitions

- A finding **hits** a defect if it is in the same file (the path at the head,
  so renames match under the new name) and its line range overlaps the defect's
  range widened by k lines on each side. k = 2 is the headline; 0 and 5 are
  reported alongside it as sensitivity.
- The arm's **reported** findings are those with `change_status == "new"` (in the
  head, not in the base). `existing` and `fixed` findings are recorded, never
  reported; a finding that could not be classified against the base is never
  treated as new — the same rule production follows.
- Recall = defects hit / defects. Precision = reported findings that hit a defect
  / reported findings. Both are `null` (never 0 or 1) with an empty denominator.
  Location accuracy = of the true positives, the share that also overlap the
  defect with k = 0. Duplicate = a reported finding whose `identity_key` was
  already reported. Findings per changed line = reported / lines the change added.

## Rules (enforced where possible)

1. **Dependency direction.** The harness may import `analysis/`; it must not
   import `app/`, and nothing in `services/ai-review/app` or `analysis` may
   import `evaluation/` (`services/ai-review/tests/test_scope_guards.py`,
   both directions, each proven to fail on a violation).
2. **Arms never see ground truth.** `load_case` returns `CaseInputs` (no ground
   truth attribute) separately from the labeled defects.
3. **Ground truth is never a model judging a model** (executable tests >
   mutation-seeded defects > verified real defects > independent human labels).
   The schema's `verified_by.method` has no model-based option.
4. **No single "overall score"**, and no raw confidence decimals presented to
   users. Report proportions with their Wilson interval.
5. **Label arms honestly.** Arm A is "ESLint + Codentry baseline ruleset (6
   rules) run with Semgrep {version}", pinned by `ruleset_sha256` in `run.json`.
6. **Nothing here is a result** until a report says so with its limitations.

## Known limitations (read before quoting any number)

- **Matching is by location only.** It cannot tell whether a finding describes
  the defect or merely sits on the same line (in `fx-001`, an unused-variable
  warning on the `eval` line counts as a hit). Precision here is an upper bound
  until findings are adjudicated by people.
- **Offline diff.** With no GitHub patch available, changed lines come from a
  local `difflib` comparison; it can differ from `git diff` by a blank line, which
  slightly moves `changed_lines` and `in_diff`.
- **The arm ignores any configuration in a case.** It runs Codentry's baseline
  rules only, by design; results say nothing about registry-scale rulesets.
- **Tool timeouts are recorded, not hidden.** Each tool has a 30 s limit; on a
  slow or loaded machine a case can finish `partial` or `failed`. That status is
  written into `result.json` and counted in `run.json`; it is never scored as a
  clean run.
- **Hashes are over file bytes.** The root `.gitattributes` pins the ruleset and
  baseline config to LF, and `cases/.gitattributes` pins case data, so a Windows
  checkout hashes the same as Linux CI. If `git ls-files --eol` shows `w/crlf` for
  those files, re-check them out.
- **`seed` is recorded but Arm A consumes no randomness.** It is there so later
  arms and the bootstrap share one field.
- Verified only on the developer's Windows machine so far; the CI step for this
  harness has not yet run.
