# Research design (Phase 0 record)

This records the research framing the foundation was hardened *for*. It is a
design note, not a result: **no experiment has been run, no metric has been
measured, and nothing here should be quoted as a finding.** The literature
survey was revised separately on 24 September 2026
([updated survey](literature-survey-updated-2026-09-24.pdf),
[change log](literature-survey-change-log-2026-09-24.md)); this design note
predates that revision and should be reconciled with it when the harness is
built. The wider product and plan documents are [PROJECT_STATUS.md](PROJECT_STATUS.md)
and [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md).

## Research question

> Do differential static analysis and optional AI review each catch real defects
> in pull requests, how much do they overlap, and how much noise does each
> add?

Working title of the contribution: *an evidence-first GitHub pull-request
analysis system that combines differential static analysis with optional AI
review and empirically evaluates the accuracy, overlap, and noise of each
review signal.* The AI reviewer is one optional, later signal — not the product
and not the contribution.

## Arms

| Arm | Signal | Status |
|---|---|---|
| A | ESLint + Codentry's Semgrep baseline ruleset, differential (new-only) | **Implemented (Phase 0)**, unmeasured |
| B | AI review only | Future. Not implemented. |
| C | Static analysis + AI | Future. Not implemented. |
| D | A second, independent model | **Explicitly not now.** |

Arm A must always be labeled "ESLint + Codentry baseline ruleset (6 rules) run
with Semgrep {version}" — never "Semgrep's performance"
(`analysis/semgrep-rules/README.md`).

## Ground truth (in order of preference)

1. Executable tests that fail before a fix and pass after.
2. Mutation-seeded defects (known by construction, scalable; realism is a
   threat).
3. Verified real defects (bug-fix commits with independent confirmation).
4. Independent human labels (more than one labeler; report agreement).

**Never** a model judging a model. In particular, Claude must not be the
ground-truth labeler for Claude's own output: same-model errors are correlated,
which would make the AI arm look better than it is.

## Metrics

Per arm, reported separately: precision, recall, false positives **per PR**
(a per-finding "false-positive rate" is ill-defined without a denominator of
true negatives), findings per changed line, location accuracy (does the finding
point at the defective lines), duplicate rate, latency, and cost. Report
overlap between arms explicitly.

**No single "overall AI score."** No raw confidence decimals shown to users.
Report uncertainty: with small N the intervals are wide (e.g. n = 30 and an
observed precision of 0.6 gives a 95% Wilson interval of roughly 0.42–0.75), so
claims must be stated with their interval.

## What Phase 0 changed to make this measurable

- **Differential analysis** so "findings per PR" means *introduced by the PR*,
  not "everything in the files it touched".
- **Line-independent finding identity** so the same problem is the same finding
  across runs, and duplicates are countable.
- **Reproducibility metadata** on every run (`review_runs.analysis_meta`): tool
  versions, ruleset SHA-256, baseline-config SHA-256, config source, snapshot
  SHAs, skip reasons.
- **Completeness tracking** so an incomplete review is `partial`, not silently
  counted as a clean one (a false "0 findings" would inflate precision).
- **Trusted, PR-independent rules** so an arm's configuration cannot be altered
  by the change being evaluated.

## Threats to validity (known now)

- **Ruleset dependence:** a six-rule Semgrep baseline understates static
  analysis; results say nothing about registry-scale rulesets.
- **Contamination:** public repositories may be in a model's training data.
- **Mutant realism:** seeded defects may not resemble real ones.
- **Small N** and labeler bias.
- **Same-model correlation** if any AI judgment enters the ground truth.
- **Task-type and authorship confounding** in any human-vs-AI-authored comparison.
- **Configuration sensitivity:** results depend on the ESLint baseline.

## Scope boundary

Codentry is not CodeArena, a coding-assessment platform, an online judge, or a
trainer. None of that code belongs here, and `tests/test_scope_guards.py`
checks the repository for it. The evaluation harness lives under `evaluation/`
(core built; see its README) and must never be imported by production code.
