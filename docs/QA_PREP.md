# Q&A preparation (Day 8)

**Status: drafted ahead of the final numbers.** The four questions the plan names are
answered here in terms that do not depend on the exact figures in
`evaluation/reports/<date>-arm-a.md` — fill in the bracketed numbers once that report
exists, and re-check each answer still matches it. Rehearsing with someone who did not
build the system is the actual Day 8 task; this is the starting script, not a substitute.

## "Why not just use an AI reviewer?"

Four independent reasons, each sourced (see §4 of `docs/PROJECT_STATUS.md` and the
updated literature survey):

1. **No independent ground truth.** An AI reviewer's own opinion can't validate itself;
   the only way to know if it's any good is to measure it against defect labels it never
   produced — which is what this project built the harness to do.
2. **Non-determinism.** The same prompt can return different code between runs; a single
   AI run is not a measurement (survey refs [46]–[48]), which is why any AI arm would
   need 3 runs per case, not 1.
3. **Noise.** Industrial deployments of LLM review report "faulty reviews, unnecessary
   corrections, and irrelevant comments" (survey ref [40]); counting that requires stable
   finding identity, which static analysis alone already needed to build correctly.
4. **Untrusted input.** A reviewer that reads repository content is a prompt-injection
   target with elevated permissions (survey refs [56]–[58]) — a risk this project
   measures (three injection fixtures in the Arm B design) rather than assumes away.

None of this says AI review is bad — it says it is a **claim to be measured**, not a
premise to build on. That is the whole thesis.

## "Why are the numbers low / high?"

Say which stratum is being asked about — they are never pooled, and "the numbers" means
different things in each:

- **Mutation logic** `[recall k=2: __/__]`: a six-rule hand-written ruleset (ESLint
  `eslint:recommended` + Codentry's six Semgrep rules) is not expected to catch
  off-by-ones, flipped operators, or dropped guards — those are semantic, not syntactic,
  defects. Low recall here is the expected result, stated as a finding in Day 4's plan
  before any number was measured ("a 0/20 result would still bound recall below 0.161").
- **Rule-aligned injections** `[recall k=2: __/__]`: expected to be high — these are
  literally the patterns the six rules target. This stratum is reported **separately**
  for exactly this reason: pooling it with logic mutants would inflate the headline.
- **Real defects (BugsJS)** `[recall k=2: __/__]`: small sample (30 cases, 7 projects);
  the interval is wide — quote it, not just the point estimate.
- **Precision / false positives per PR**: **not computed** — this needs the human
  adjudication in `evaluation/labeling/`, which has not happened yet. Say this plainly
  rather than improvising a number.

## "What is not implemented?"

Lead with the honest list, not a defensive one: any AI/LLM review (gated, not built —
`docs/AI_ARM_DESIGN_AND_COST.md`), human-adjudicated precision, a real GitHub → Supabase →
Render → Vercel run (`docs/REAL_RUN_LOG.md`), a Vercel-side webhook inbox, a real sandbox
for analysis (scrubbed env + resource limits, not containerization), comment posting to
GitHub (deliberately, not a gap), and anything beyond JavaScript/TypeScript.

## "What would you do with another month?"

In priority order, matching the plan's own cut list (reversed): adjudicate a larger
sample and report real precision; run the real GitHub/Supabase/Render/Vercel end-to-end
path; if a spending-capped API key and labeled ground truth both exist, build the gated
AI arm and the Arm C overlap/independence analysis for real; extend the mutation
operator set and the real-defect corpus past BugsJS's test-result-bearing projects;
re-run with a larger noise-PR sample. Each of these is already designed (the schema, the
scoring, the labeling protocol, or the Arm C arithmetic exists) — the limiting factor is
time and people, not missing design.

## Likely follow-ups

- **"Why six Semgrep rules and not the registry?"** Scope and auditability: every rule
  has a documented true/false-positive test, and the arm is labeled "Codentry baseline
  ruleset (6 rules)," never "Semgrep's performance," so nobody mistakes a narrow
  ruleset's recall for a statement about static analysis in general.
- **"Couldn't a model have labeled the findings instead of two people?"** No — that
  would be a model judging a model (or judging static analysis with no independent
  check), which correlates errors with whatever produced the findings. The protocol
  requires two independent human labelers and reports their agreement (Cohen's κ).
- **"Is BugsJS contaminated — could a model have seen these bugs and fixes?"** Likely,
  for a future AI arm — these are public projects and a public benchmark. This is stated
  as a threat to validity, not hidden; it's also why the mutation corpus exists (no
  external dataset can be contaminated the same way, since the defects are
  seeded by this project's own generator, though the *source* files are still public).
- **"Why does static analysis without AI count as a contribution?"** The contribution is
  the harness and its honesty properties (differential analysis, line-independent
  identity, reproducible runs, per-stratum reporting, never a model judging a model) —
  not a claim that six rules are a good reviewer. Arm A is the first signal measured
  through that harness, not the point of it.
