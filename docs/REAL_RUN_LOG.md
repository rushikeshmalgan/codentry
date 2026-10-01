# Real-run log — GitHub → Supabase → Render → Vercel (Day 6, Track G)

**Status: not done. Raw evidence below is a template, not a result.**

## Why

Track G (`docs/8_DAY_IMPLEMENTATION_PLAN.md` Day 6) asks for one real pull request to be
opened against a live deployment, with the delivery, job, and finding rows recorded
verbatim. That needs:

- a Supabase project (the four migrations applied to it, `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY`),
- a GitHub App registered and installed on a disposable test repository,
- a Render deployment of `services/ai-review`,
- a Vercel deployment of `apps/web`,

none of which exist. No account was created or signed into for this project at any point;
this assistant has no credentials for Supabase, Render, Vercel, or a GitHub App
registration, and creating any of these is explicitly **USER ACTION** in the plan. This
log is therefore the template the plan asks for in its place ("an explicit statement that
it was not done and why"), so the team can run it once and paste the real output in.

## What exists instead (local, mocked GitHub — labeled as such)

`services/ai-review/tests/test_review_runner.py` and the webhook/job tests in
`services/ai-review/tests/` exercise the full pipeline — webhook receipt → job claim →
pinned snapshot → differential analysis → finalize — against a **mocked** GitHub HTTP
layer (`respx`) and, in most environments, an in-memory store; they use the real ESLint
and Semgrep. They prove the code paths run; they are not evidence that GitHub, Supabase,
Render, or Vercel work together, and are not a substitute for Track G.

## How to run it (follow `docs/first-deployment-runbook.md` in order)

1. **Supabase.** Create a project; apply migrations `0001`–`0004` in order via the SQL
   Editor. Record any error **verbatim** (migration `0004` has never been run against a
   live database before this).
2. **GitHub App.** Register it on a disposable test repository (not a real project).
3. **Render.** Deploy `services/ai-review`; warm it (a cold start can exceed GitHub's
   10-second webhook timeout — hit `/api/status` once before opening the PR).
4. **Vercel.** Deploy `apps/web`, pointing its webhook secret and backend URL at the
   above.
5. Open one pull request on the test repository. Record, with exact values:

| Step | Expected | Observed |
|---|---|---|
| Webhook delivery accepted | HTTP 202 | *(not run)* |
| `webhook_deliveries.status` | `succeeded` | *(not run)* |
| `review_runs.status` | `completed` or `partial` | *(not run)* |
| Findings | rows with a `change_status` (`new`/`existing`/`fixed`) | *(not run)* |
| Redelivery (GitHub "Redeliver") | second delivery → `duplicate_ignored`, no second job | *(not run)* |
| Any migration `0004` SQL error | — | *(not run)* |
| Render cold-start time vs. GitHub's 10 s webhook timeout | — | *(not run)* |

6. Paste raw table rows / log lines here, not a summary. If something fails, record the
   failure as-is — a partially working run must not be described as verification
   (`docs/8_DAY_IMPLEMENTATION_PLAN.md` Day 6, task 3).

## Arm C (Day 6, task 1)

Separate from Track G: `evaluation/runners/arm_c_union.py` computes the overlap,
McNemar test, and independence estimate between two arms' evaluation runs. Since Arm B
does not exist (Day 5's gate did not open — `docs/AI_ARM_DESIGN_AND_COST.md`), running it
without `--arm-b-run` writes the analysis *plan* instead of fabricating a second arm's
numbers, exactly as the plan's fallback instructs ("If Arm B was skipped, produce the
analysis plan and stop"). See `evaluation/reports/` for the plan JSON once Day 4's full
run has produced an Arm A directory to point it at.
