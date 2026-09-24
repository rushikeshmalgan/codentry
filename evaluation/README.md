# evaluation/

**Phase 0: documentation only. No code here yet, by design.**

This directory is reserved for the evaluation harness — the later phase that
measures the precision, recall, false positives per PR, location accuracy,
duplicate rate, latency, and cost of each review signal. See
[`../docs/research-design.md`](../docs/research-design.md) for the research
question, arms, ground-truth rules, and metrics.

## Planned layout (conceptual — nothing below exists yet)

```
evaluation/
  datasets/   pinned PR corpora + provenance (repo, base SHA, head SHA, license)
  cases/      one directory per case: the change, the ground-truth defects, how each was established
  runners/    run one arm (A: static, later B/C: AI) against a case, from a pinned snapshot
  metrics/    precision/recall/FP-per-PR/location accuracy/duplicate rate/latency/cost + intervals
  reports/    generated, dated, reproducible outputs (never hand-edited)
```

## Rules (enforced where possible)

1. **Separate from production.** Nothing in `services/ai-review/app` or
   `services/ai-review/analysis` may import from `evaluation/`
   (`tests/test_scope_guards.py`). The harness may import from production; never
   the reverse.
2. **Phase 0 contains no Python.** The same test fails if a `.py` file appears
   here before the harness phase deliberately begins.
3. **Ground truth is never a model judging a model** (executable tests >
   mutation-seeded defects > verified real defects > independent human labels).
4. **No single "overall score"**, and no raw confidence decimals presented to
   users.
5. **Label arms honestly.** The static arm is "ESLint + Codentry baseline
   ruleset (6 rules) with Semgrep {version}", pinned by
   `analysis_meta.ruleset_sha256`.
6. **Nothing here is a result.** No experiment has been run.
