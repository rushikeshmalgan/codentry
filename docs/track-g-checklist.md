# Track G checklist — one real pull request, checked end to end

**USER ACTION.** Run this once, after `docs/first-deployment-runbook.md` Steps 1–4
(Supabase, Render, Vercel, GitHub App). The assistant creates no accounts and holds no
credentials; everything below runs on your machine with your keys.

**Blocked until a decision:** the runbook's Step 1.6 says not to connect a GitHub App to a
Supabase project whose Data API is still open to the anon key (`docs/architecture.md`
gap #10). Apply the reviewed lockdown migration first; the `anon_data_api_closed` check
below confirms it on the real project.

The checks are scripted: `services/ai-review/scripts/track_g_check.py` (standard library
only, read-only GET requests, credentials from environment variables, never printed).

## 0. Environment (your shell only; never commit these)

```
export SUPABASE_URL=...               # Project URL
export SUPABASE_SERVICE_ROLE_KEY=...  # service_role key (read access for the checks)
export SUPABASE_ANON_KEY=...          # anon key, to prove the Data API is closed to it
export RENDER_URL=https://<your-render-service>.onrender.com
export VERCEL_URL=https://<your-vercel-project>.vercel.app
cd services/ai-review
```

(PowerShell: `$env:SUPABASE_URL = "..."` and so on.)

## 1. Cold start (do this first, on an idle service)

Render's free tier spins an idle service down (at the time of writing, after about 15
minutes without traffic; check Render's current docs). Leave it untouched for at least
that long, then:

```
python scripts/track_g_check.py --repo <owner>/<test-repo> --pr 0 --cold-start \
  --markdown ../../docs/REAL_RUN_LOG.md
```

`render_cold_start` records the seconds to the first `/health` response and compares them
with the Vercel forward budget (8.3 s: 4 s + 0.3 s + 4 s in `apps/web/lib/internal-client.ts`)
and GitHub's 10 s webhook timeout. The database checks fail here (PR #0 does not exist);
only the Render lines matter for this run.

## 2. Open the pull request

On the **disposable** test repository the App is installed on, open a PR that contains at
least one thing the ruleset flags (for example a line using `eval(...)` in a `.js` file),
so the findings check has rows to look at. Wait for Render's logs to show
`review_run_completed`/`partial`/`failed` (a minute or two).

```
python scripts/track_g_check.py --repo <owner>/<test-repo> --pr <n> \
  --markdown ../../docs/REAL_RUN_LOG.md
```

| Check | Passes when |
|---|---|
| `render_health`, `render_worker` | `/health` is 200 and the worker thread is running |
| `vercel_status`, `vercel_webhook_route` | Vercel reports the backend `ok`; `GET /api/github/webhook` is 405 |
| `repository_row`, `pull_request_row` | the installation and PR reached Supabase, with the PR's head SHA |
| `one_review_run_per_head` | at most one review run per (PR, head SHA) |
| `review_run_status`, `review_run_recorded` | the run ended `completed` (or `partial`, with reasons shown) and recorded its merge base and `analysis_meta`; `pending`/`running` is INFO: re-run in a minute |
| `findings` | rows with `change_status` new / existing / fixed |
| `webhook_deliveries` | the newest `pull_request` delivery `succeeded`; none `failed`, `retryable`, or stuck in `processing` |
| `anon_data_api_closed` | the anon key gets 401/403 from the Data API |

Also confirm by eye: GitHub App → Advanced → Recent Deliveries shows the delivery with a
2xx response (the receiver answers 202).

## 3. Redelivery

In Recent Deliveries, open that PR's delivery, copy its GUID, click **Redeliver**, then:

```
python scripts/track_g_check.py --repo <owner>/<test-repo> --pr <n> \
  --after-redelivery <GUID> --markdown ../../docs/REAL_RUN_LOG.md
```

`redelivery_dedup` passes when that delivery is `succeeded` and there is still exactly one
review run for the head SHA (the redelivery did not start a second review).

## 4. Record

The `--markdown` runs append their tables to `docs/REAL_RUN_LOG.md`. Commit that file with
the raw tables as they are; a failed check is recorded as failed, not summarized away
(`docs/8_DAY_IMPLEMENTATION_PLAN.md` Day 6). Exit status: 0 when nothing failed.

## How the script itself was verified

VERIFIED LOCALLY, not against real services: unit tests with a scripted fake of all three
services (`tests/test_track_g_check.py`, including "no secret ever appears in the output");
the database checks run against the local Supabase stack seeded through the service's own
code path (all PASS; `anon_data_api_closed` FAIL, correctly, because gap #10 is open
there); the Render checks run against the production image started locally. The Vercel
checks have only run against the fake.
