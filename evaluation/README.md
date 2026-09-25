# evaluation/

The offline evaluation harness. **Status: Days 1–3 of the plan.**

- **Day 1** — a deterministic pipeline from a case directory, through Arm A (static
  analysis), to a metrics record.
- **Day 2** — a seeded generator of mutation cases over third-party open-source code.
- **Day 3** — real-defect cases (BugsJS fixes, reversed), pull requests for noise
  measurement, and a labeling protocol with a calibration round ready for two people.

There is **no AI arm, no aggregate report, and no measured result.** `cases/` holds
237 cases in four families, always reported separately, never pooled:

| Prefix | Stratum | Count | What it is | Ground truth |
|---|---|---|---|---|
| `fx-` | `fixture:*` | 2 | hand-made harness self-tests — **not evidence** | hand-labeled |
| `mut-` | `mutant:logic`, `mutant:rule-aligned` | 130 + 39 | one seeded edit to a real file | by construction |
| `bug-` | `real:bugsjs` | 30 | a real bug's fix **reversed** (base = fixed, head = buggy) | BugsJS, manually validated |
| `pr-` | `noise:pr` | 36 | recently merged pull requests | **none** (unlabeled) |

Nobody has scored Arm A over these cases, and nobody has labeled any finding.

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
Semgrep twice (base and head). **Running Arm A over all 237 cases therefore takes
on the order of 1–1.3 hours as the CLI stands.** Only 13 distinct originals underlie
the mutation corpus, so analyzing each base once and batching heads is the obvious
speed-up, left for when a full run is needed (plan Day 4). The harness tests take a
few minutes because they run the real tools on the two fixtures, including two full
CLI runs that must match byte for byte.

## Layout

```
evaluation/
  schema/case.schema.json   the case format (JSON Schema, draft 2020-12)
  case.py                   load + validate a case; CaseInputs (what an arm may see) vs ground truth
  diffing.py                head-side changed ranges: the harness's one definition of "where"
  cases/<case-id>/          case.json, base/…, head/…   (bytes pinned by cases/.gitattributes)
  runners/arm_a_static.py   Arm A: runs analysis.snapshot_analysis on a case (the production code path)
  record.py                 per-case result record: findings + how they score
  metrics/matching.py       finding ↔ defect matching, ±k tolerance, duplicates
  metrics/stats.py          Wilson interval, exact McNemar, Cohen's kappa, seeded bootstrap
  run.py                    the CLI
  datasets/                 provenance — see below (manifests, vendored sources, license texts)
  generators/               the seeded mutation engine (Day 2)
  labeling/                 protocol, item builder, agreement checker, calibration round (Day 3)
  THIRD_PARTY_NOTICES.md    license texts that must accompany the redistributed code
  tests/                    harness tests
  reports/                  (created by you) run outputs; never hand-edited
```

Every case family has a manifest of hashes that tests verify offline:
`datasets/manifest.json` (mutation sources), `datasets/bugsjs.json` (real defects),
`datasets/noise_prs.json` (pull requests). The acquisition scripts —
`fetch_sources.py`, `bugsjs.py`, `noise_prs.py` — are the **only** network use in the
harness, are run once by a person, and are never run by tests. `licensing.py` checks
every license *text* (MIT, ISC and CC0-1.0 are accepted; anything else stops an import)
and each manifest records how.

## The mutation corpus (Day 2)

Thirteen files from seven permissively licensed open-source projects
(validator.js, node-semver, ms, minimist, uuid, p-retry, p-limit; MIT/ISC), each
pinned to a commit and SHA-256. From each file the generator makes up to 10
`mutant:logic` cases and 3 `mutant:rule-aligned` cases; a case is the original file
(`base/`) and the same file with **one** edit (`head/`), and the edit's line is the
ground truth.

```bash
PYTHONPATH=services/ai-review python -m evaluation.generators.build_cases            # regenerate
PYTHONPATH=services/ai-review python -m evaluation.generators.build_cases --verify   # byte-identical?
```

- **Logic operators (8):** relational flip, equality flip, `&&`↔`||`, negate a condition,
  drop an early-exit guard, remove an `await`, off-by-one, change an integer constant.
- **Rule-aligned injections (4):** one inserted line of `eval(p)`, SQL string
  concatenation, a hardcoded secret, or `innerHTML = p`. These are patterns Arm A's
  six Semgrep rules target, so this stratum is **expected to favor Arm A and must
  never be pooled** with the logic stratum.
- **Determinism:** seeded from (global seed, file, stratum); same manifest, seed and
  TypeScript version reproduce every case byte for byte. No language model is involved.
- **Validity:** every mutant parses and its recorded line range equals the range of an
  independent line diff, or it is discarded.

Cannot tell you: mutants are a **proxy** for real faults; equivalence is `unchecked`;
they are checked for syntax only; the sources are popular libraries a model may have
seen; `remove-await` has one mutant, so per-operator results would mean nothing; 13
files is a small, clustered sample (mutants from one file are not independent).

## The real-defect corpus (Day 3)

Thirty cases from BugsJS (Gyimesi et al., ICST 2019 — survey ref [54]), a benchmark of
manually validated bugs from real Node.js projects: Express 8, Karma 6, ESLint 6, Hexo 5,
Hessian.js 2, Bower 2, Shields 1 (MIT; Shields CC0). For each bug BugsJS publishes the
buggy revision and a cleaned fix. A case **reverses** the fix: `base` = the fixed file,
`head` = the buggy file, so the "pull request" reintroduces the bug, and the ground truth
is where the fix changed code (14 of the 30 fixes touch more than one place; all locations
of one bug share a `group`, and recall counts the bug once).

Selection is mechanical and recorded in `datasets/bugsjs.json`: the fix changes exactly
one JavaScript source file, in at most 3 hunks and 20 changed lines, and git's diff and the
harness's independent diff agree on the hunks; then a seeded sample per project. A
committed test re-derives every case's ground-truth ranges from its two files.

```bash
PYTHONPATH=services/ai-review python -m evaluation.datasets.bugsjs \
    --work <cache-dir> --bug-dataset <clone of BugsJS/bug-dataset>   # one-time; needs network
```

Cannot tell you, and the manifest says so:

- **Reversal is not a natural pull request** — the shape of the change is a fix undone.
- **Executable evidence is thin.** Only **10 of the 30** cases carry a *recorded* failing
  test (BugsJS's own run of the buggy revision with the fix's tests added); the other **20**
  (Karma, ESLint, Bower, Shields, and some Express/Hexo bugs) rest on BugsJS's manual
  validation alone, because this dataset snapshot ships no test results for them. Each case
  says which. **No project test suite was run here** — the plan's optional execution
  spot-check was not done (running old third-party test suites means installing and
  executing old dependencies); we fell back to the dataset's own validation, as the plan
  allows.
- **Contamination is likely:** these are popular public projects and BugsJS is public.
- Selection favors small, localized, single-file bugs.
- The ground truth is the fix's location; a finding elsewhere that also points at the bug
  is scored as unmatched.

## The noise-measurement pull requests (Day 3)

Thirty-six merged pull requests from three active MIT-licensed repositories (fastify 12,
axios 12, zod 12), for measuring **findings per pull request, the new-vs-existing share,
the duplicate rate and identity stability**. They have **no defect labels**
(`ground_truth_status: unlabeled`), so recall and precision are `null` for them — never 0
or 1. A "pull request" is derived from history alone (a squash commit titled `… (#N)`:
first parent → that commit), starting at a commit pinned per repository, taking the most
recent ones that qualify (1–6 JS/TS files, ≤ 300 changed lines, files ≤ 60 KB).

Cannot tell you: three well-maintained libraries are not typical student code; the
selection is mechanical, so it includes trivial pull requests (release bumps, sponsor
lists) alongside real changes; a squash commit may differ from what a reviewer saw; and
the sample is small and clustered by repository.

## Labeling (Day 3) — see `labeling/protocol.md`

Precision cannot be computed from unlabeled findings, and an *unmatched* finding is not
automatically a false one: it may be a real issue the ground truth does not list. So
people label findings — `real issue` / `not an issue` / `unclear` — **two independent
labelers per item, blind to the arm, never a model**, and agreement is reported as
Cohen's κ (also with `unclear` merged into `not an issue`).

`labeling/calibration/calibration-01.sheet.md` holds a **10-item calibration round**
sampled from real Arm A findings on the noise pull requests (a seeded sample, at most 3
per case); blank sheets are in `labeling/labels/`. **Nobody has labeled it yet** — that is
the team's task, and the plan's Day 3 acceptance criterion (one labeler pair completes it)
is open until they do. The sample is narrow: 7 of the 10 items are one TypeScript rule
(`no-explicit-any`), because that is what Arm A reported on these pull requests.

```bash
PYTHONPATH=services/ai-review python -m evaluation.labeling.agreement \
    --items evaluation/labeling/calibration/calibration-01.items.json \
    --a evaluation/labeling/labels/calibration-01.labeler-a.csv \
    --b evaluation/labeling/labels/calibration-01.labeler-b.csv
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

- A finding **hits** a defect location if it is in the same file (the path at the head,
  so renames match under the new name) and its line range overlaps the location widened by
  k lines on each side. k = 2 is the headline; 0 and 5 are reported as sensitivity.
- The arm's **reported** findings are those with `change_status == "new"` (in the
  head, not in the base). `existing` and `fixed` findings are recorded, never
  reported; a finding that could not be classified against the base is never
  treated as new — the same rule production follows.
- A **defect** is a *group* of locations (one for most cases; several for a bug fixed in
  several places). **Recall** = defects with at least one location hit / defects.
- A reported finding that hits a location is **matched**; one that hits none is
  **unmatched** — *not* "false positive": that word is reserved for findings people have
  adjudicated. **Precision** here = matched / reported (location-matched, see below).
- All of these are `null` (never 0 or 1) with an empty denominator, and for
  `unlabeled` cases recall, precision and location accuracy are always `null`.
- Location accuracy = of the matched findings, the share that also overlap the defect with
  k = 0. Duplicate = a reported finding whose `identity_key` was already reported.
  Findings per changed line = reported / lines the change added.

## Rules (enforced where possible)

1. **Dependency direction.** The harness may import `analysis/`; it must not
   import `app/`, and nothing in `services/ai-review/app` or `analysis` may
   import `evaluation/` (`services/ai-review/tests/test_scope_guards.py`,
   both directions, each proven to fail on a violation).
2. **Arms never see ground truth.** `load_case` returns `CaseInputs` (no ground
   truth attribute) separately from the labeled defects.
3. **Ground truth is never a model judging a model** (executable tests >
   mutation-seeded defects > verified real defects > independent human labels).
   The schema's `verified_by.method` has no model-based option, and no model may label.
4. **No single "overall score"**, and no raw confidence decimals presented to
   users. Report proportions with their Wilson interval.
5. **Label arms honestly.** Arm A is "ESLint + Codentry baseline ruleset (6
   rules) run with Semgrep {version}", pinned by `ruleset_sha256` in `run.json`.
6. **Nothing here is a result** until a report says so with its limitations.
7. **Every redistributed file has a recorded license** whose text was machine-checked and
   is reproduced in `THIRD_PARTY_NOTICES.md`.

## Known limitations (read before quoting any number)

- **Matching is by location only.** It cannot tell whether a finding describes the defect
  or merely sits on the same line (in `fx-001`, an unused-variable warning on the `eval`
  line counts as a hit), which inflates precision; and an unmatched finding may be a real
  issue the ground truth does not list, which deflates it. Location-matched precision is
  neither an upper nor a lower bound until findings are adjudicated by people.
- **Offline diff.** With no GitHub patch available, changed lines come from a local
  `difflib` comparison; it can differ from `git diff` by a blank line, which slightly moves
  `changed_lines` and `in_diff`.
- **The arm ignores any configuration in a case.** It runs Codentry's baseline
  rules only, by design; results say nothing about registry-scale rulesets.
- **Tool timeouts are recorded, not hidden.** Each tool has a 30 s limit; on a slow or
  loaded machine a case can finish `partial` or `failed` (seen during Day 3: one noise
  case ended `partial` on a Semgrep timeout and completed on another run). That status is
  written into `result.json` and counted in `run.json`; it is never scored as a clean run,
  and labeling never samples from an incomplete analysis.
- **Hashes are over file bytes.** The root `.gitattributes` pins the ruleset and baseline
  config to LF, and `cases/`, `datasets/` and `labeling/` pin their own data, so a Windows
  checkout hashes the same as Linux CI. If `git ls-files --eol` shows `w/crlf` for those
  files, re-check them out.
- **`seed` is recorded but Arm A consumes no randomness.** It is there so later
  arms and the bootstrap share one field.
- **Verified on one Windows machine and, for the Day 1 harness, on Linux CI.** The Day 2–3
  additions have not run in CI yet.
