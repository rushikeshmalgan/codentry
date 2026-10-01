# Final results — Arm A, 2 October 2026

**Status: drafted from the real report** (`evaluation/reports/2026-10-02-arm-a.md`,
results SHA-256 `157afe6b1fbf0f1ec266c5e2527eabb5c5c7eda56b76e794ffeb41251cab6ac0`,
reproduces via `python -m evaluation.repro --run … --no-rerun --report-md … --report-json …`).
This is the Day 8 write-up draft; re-check it against the report if either changes, and
have the team read it before the literature-survey/FYP-report reconciliation (task 2).

## What was measured

Arm A — "ESLint + Codentry baseline ruleset (6 rules) run with Semgrep 1.177.0" — over
237 cases in four strata, never pooled:

| Stratum | Cases | What it answers | Recall (k=2, matched defects) |
|---|---|---|---|
| `mutant:logic` | 130 (129 completed) | Can the ruleset see seeded semantic bugs? | **2/129 = 1.6%** (95% CI 0.4–5.5%) |
| `mutant:rule-aligned` | 39 | Does the ruleset catch the patterns it targets? | **39/39 = 100%** (95% CI 91–100%) — expected, reported apart |
| `real:bugsjs` | 30 | Can it see real, previously-fixed bugs? | **1/30 = 3.3%** (95% CI 0.6–16.7%) |
| `noise:pr` | 36 | How much does it say on ordinary merged PRs? | n/a — unlabeled, volume only |

One case (`mut-plimit-index-l10`) hit a Semgrep timeout and is excluded from every
number above, not counted as clean.

## The headline finding

**A six-rule hand-written ruleset essentially cannot detect semantic logic defects.**
Of eight mutation operators (relational flip, equality flip, `&&`/`||` swap, negate-
condition, drop-guard, remove-await, off-by-one, constant-change), only `drop-guard`
was ever detected (2 of 19 cases) — and both detections were incidental: the missing
guard left dead code that `no-unused-vars` or `no-empty` happened to flag, not a rule
recognizing "a guard was removed here." The other seven operators scored zero across
110 cases. Real BugsJS bugs fare similarly (1/30).

This was predicted, not discovered after the fact: the plan's Day 4 entry stated before
any case was run, "Expect low recall — a small hand-written ruleset is unlikely to
detect logic mutants or most real bugs; that is a finding, not a failure." The data
matches that prediction closely.

By contrast, the rule-aligned stratum — a line of `eval()`, a hardcoded secret, SQL
string concatenation, or an `innerHTML` assignment inserted into otherwise-real code —
is caught 100% of the time, because that is literally what the six rules look for. The
two strata measure different things and must never be reported as one number.

On the 36 real merged pull requests (no defect labels — a volume measure, not a recall
one), **95.7%** of findings on touched files were pre-existing (`existing`, not `new`):
most of what a whole-file review would have blamed on the change was already there
before it — evidence for why differential analysis (Phase 0's core contribution)
matters independently of how good any one detector is.

## Identity stability

877 real findings (from the real-defect and pull-request corpora) were re-analyzed
after a 3-line shift and, separately, after adding trailing whitespace to every line.
**100% kept the same `identity_key` under both transformations.** This is the expected
result for a ruleset with no whitespace-sensitive rules, now verified on real tool
output rather than asserted from the identity design alone.

## Not measured

**Precision and false positives per pull request.** These need people: across the full
run there are only 40 unmatched `new` findings (well under the 150-case cap), and a
30-item adjudication sample is built and ready
(`evaluation/labeling/calibration/main-01.*`), but nobody has labeled it, and nobody has
labeled the Day 3 calibration round either. Until that happens, "unmatched" means only
"did not overlap a known defect's location" — not "wrong." Some unmatched findings may
be real issues the ground truth doesn't list; some location matches may be coincidental
(see the `drop-guard` example above).

**Anything about AI review.** Arm B was gated and the gate did not open — no adjudication
protocol in active use, no spending-capped API key (`docs/AI_ARM_DESIGN_AND_COST.md`
covers the design and a cost estimate instead). Arm C (overlap/independence analysis) is
implemented and tested, but produces only a documented analysis plan, since there is no
second arm to compare against (`evaluation/runners/arm_c_union.py`).

**A real GitHub → Supabase → Render → Vercel run.** Not attempted; no accounts exist for
any of these services (`docs/REAL_RUN_LOG.md`).

## Threats to validity

- **Small N, clustered.** 130 mutation-logic cases come from only 13 source files; 30
  real-defect cases from 7 projects; 36 noise PRs from 3 repositories. Cases from the
  same file or project are not independent trials, so the Wilson intervals (which assume
  independence) understate the true uncertainty.
- **Mutant realism.** Mutation-seeded defects are a proxy for real faults; equivalence is
  unchecked (some "mutants" may not change behavior at all).
- **Six-rule ruleset, not "static analysis."** Results bound what this specific baseline
  does; they say nothing about Semgrep's registry rules, other linters, or static
  analysis as a category.
- **Location-only matching.** A hit can be coincidental (demonstrated above); a miss can
  undercount a finding that points at the right problem from a different line. Precision
  is therefore neither an upper nor a lower bound until adjudicated.
- **Labeler bias (not yet applicable — no labels exist).** When the adjudication round is
  labeled, two people from one team judging public code is a small, possibly correlated
  panel; agreement (Cohen's κ) measures whether they apply the rubric consistently, not
  whether the labels are "true."
- **Same-model concerns.** Not applicable yet (no AI arm exists); the standing rule — no
  model ever labels ground truth for a model's own output — is enforced by the schema
  (`verified_by.method` has no model-based option) and will stay enforced if Arm B is
  built.
- **Non-determinism.** Arm A is fully deterministic (same ruleset, same input, same
  output); this does not apply to it, only to a future AI arm, where the plan already
  requires 3 runs per case for this reason.
- **Configuration sensitivity.** Arm A ignores any configuration in the case under
  analysis by design (the baseline is fixed); a different baseline would likely shift
  every number above, including the headline recall figures.
- **Contamination.** Every source corpus (validator.js, node-semver, ms, minimist, uuid,
  p-retry, p-limit, Express, Karma, ESLint, Hexo, Hessian.js, Bower, Shields, fastify,
  axios, zod) is public; a future AI arm could have seen this code and its fixes during
  training. This does not affect Arm A, which has no training data.
- **Reversed-fix shape.** The 30 real-defect cases reverse a fix rather than capture a
  natural pull request; the change's shape (what surrounds it) differs from how bugs are
  really introduced.
- **Reproducibility check is partial.** The report's derivation from the recorded run is
  verified byte-for-byte. Re-running Arm A over the full 237-case corpus a second time
  (the stronger check) was not exercised this session (≈75–90 minutes); it is exercised,
  and passes, on the two-case fixture suite in CI-equivalent tests.

## What would change the numbers most

In order of expected impact: (1) adjudicating the 30-item sample, which would turn
"unmatched" into a real precision figure; (2) a richer ruleset (more Semgrep rules or a
different baseline), which the Day 4 "must not" rule explicitly forbids tuning against
these specific cases (that would be training on the test set); (3) more real-defect
cases from projects BugsJS does ship test results for, to improve the executable-evidence
share beyond today's 10/30.
