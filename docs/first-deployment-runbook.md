# First deployment runbook — from zero accounts to a verified real PR

This is the one thing to follow start-to-finish the first time. It exists
because `docs/deployment.md`, `docs/github-app-setup.md`, and
`supabase/README.md` are each organized by *service*, not by the order you
actually need to do things in — each step below feeds an env var into the
next one, so order matters. Each step links to the detailed doc for that
service; this page is the sequencing, not a replacement for them.

Total cost: $0 — every service used has a free tier sufficient for this.

---

## Step 1 — Supabase (create the database first; nothing else needs to wait)

1. Sign up at [supabase.com](https://supabase.com) (GitHub login is fine —
   this is just a Supabase account, unrelated to the GitHub *App* in Step 4).
2. Create a new project. Pick any name/region; note the database password
   somewhere safe (you likely won't need it directly — the API keys below
   are what the app actually uses).
3. In Project Settings → API, copy:
   - **Project URL** → this is `SUPABASE_URL`
   - **service_role key** (not the `anon` key) → this is `SUPABASE_SERVICE_ROLE_KEY`
4. Apply the four migrations, in order, via the SQL Editor (paste each
   file's contents and run it):
   - `supabase/migrations/0001_enable_pgvector.sql`
   - `supabase/migrations/0002_github_app_bookkeeping.sql`
   - `supabase/migrations/0003_findings.sql`
   - `supabase/migrations/0004_durable_events_and_jobs.sql` (Phase 0: durable
     webhook events + job queue; **not yet run against a live database** —
     report any SQL error verbatim)
5. Confirm in Table Editor that `installations`, `repositories`,
   `pull_requests`, `review_runs`, `webhook_deliveries`, and `findings` all
   exist (empty is fine — they just need to exist).

Full detail: `supabase/README.md`.

**Checkpoint:** you now have `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` saved somewhere (a password manager, not a file in this repo).

---

## Step 2 — Render (deploy services/ai-review)

1. Sign up at [render.com](https://render.com) (GitHub login is fine).
2. New → Blueprint → connect this GitHub repo → Render reads `render.yaml`
   and proposes the `codentry-ai-review` web service. Confirm.
   - If Render's Blueprint flow gives you trouble, create it manually
     instead — exact settings are in `docs/deployment.md` under
     "Render — services/ai-review".
3. Once created, before the first deploy finishes, go to the service's
   Environment tab and add:
   - `SUPABASE_URL` = from Step 1
   - `SUPABASE_SERVICE_ROLE_KEY` = from Step 1
     (**required**: with `ENVIRONMENT=production` the service refuses to start
     without both of these and the internal secret below)
   - `CODENTRY_INTERNAL_WEBHOOK_SECRET` = generate one yourself right now
     (e.g. `openssl rand -hex 32`, or any long random string) — **save this
     value**, you'll enter the identical string into Vercel in Step 3.
   - Leave `GITHUB_APP_ID` / `GITHUB_PRIVATE_KEY` blank for now — Step 4
     doesn't exist yet.
4. Wait for the deploy to finish. Note the service's public URL, e.g.
   `https://codentry-ai-review.onrender.com`.
5. **Verify #1 (Node available):** check the build logs for the
   `npm install` step (inside `analysis/eslint-baseline`) — confirm it
   completed without error. This is the check you asked for; if it fails
   here, see the fallback note in `docs/deployment.md`.
6. **Verify (health check):**
   `curl https://<your-render-url>/health` → should return
   `{"status":"ok",...}`.

Full detail: `docs/deployment.md`.

**Checkpoint:** Render is live, `/health` responds, and you have the Render URL.

---

## Step 3 — Vercel (deploy apps/web)

1. Sign up at [vercel.com](https://vercel.com) (GitHub login recommended —
   makes importing the repo a one-click step).
2. Import this repo as a new project. **Set Root Directory to `apps/web`**
   — this is the one setting that's easy to miss in a monorepo.
3. Before/after the first deploy, add these Environment Variables:
   - `NEXT_PUBLIC_API_BASE_URL` = the Render URL from Step 2
   - `CODENTRY_INTERNAL_WEBHOOK_SECRET` = **the exact same value** you set on Render in Step 2
   - `GITHUB_WEBHOOK_SECRET` = generate another random string now (different from the internal one) — save it, you'll enter it into the GitHub App in Step 4
4. Deploy. Note the resulting URL, e.g. `https://codentry.vercel.app`.
5. **Verify:** visit `/` — both services should show `ok`.
   `curl https://<your-vercel-url>/api/github/webhook` (a bare GET, not a
   real webhook) should return a 405 (method not allowed) or similar —
   confirms the route exists and is live, not the 501 from the old Phase 1 stub.

Full detail: `docs/deployment.md`.

**Checkpoint:** Vercel is live, and you have the Vercel URL to give GitHub next.

---

## Step 4 — Register the GitHub App

1. Follow `docs/github-app-setup.md` exactly — permissions (Pull requests
   Read&Write, Contents Read-only, Metadata Read-only) and webhook events
   (pull_request, installation, installation_repositories) matter for the
   security posture, not just functionality.
2. **Webhook URL** = `https://<your-vercel-url>/api/github/webhook`
3. **Webhook secret** = the `GITHUB_WEBHOOK_SECRET` value from Step 3.4
   (must match exactly what you put in Vercel).
4. Generate and download the private key (`.pem` file).
5. Go back to **Render** (Step 2) and now fill in the two blanks:
   - `GITHUB_APP_ID` = shown on the App's settings page
   - `GITHUB_PRIVATE_KEY` = the `.pem` contents, with real newlines replaced
     by literal `\n` (see the comment in `.env.example` for the exact format)
6. Redeploy Render so it picks up the new env vars.
7. Install the App on **one disposable test repository** — not a real
   team project yet.

**Checkpoint:** the App exists, is installed somewhere, and both Render and Vercel have every env var filled in.

---

## Step 5 — Run the actual end-to-end verification

This is where your original 8 checks get answered for real. Open a pull
request on the test repository you installed the App on, then work through
`docs/staging-test-phase2.md` section A ("End-to-end staging test") and
`docs/static-analysis.md`'s failure-behavior section if anything comes back
`failed` instead of `completed`. Specifically:

| Your check | Where to look |
|---|---|
| Node/ESLint/Semgrep work on Render | Render build logs (Step 2.5) + the review run's final status not being `failed` with an eslint/semgrep error |
| 30s timeout behavior | Only observable if a file is large/slow enough to trigger it — not expected on a normal PR; safe to skip unless you want to construct a pathological test file |
| Real PR reaches the backend | GitHub App → Advanced → Recent Deliveries shows a 202 |
| Changed files fetched via installation token | Render logs show `review_run_started` followed by `review_run_completed`/`failed` with a specific reason if auth failed |
| Findings persisted to Supabase | Table Editor → `findings` table has rows with `review_run_id` matching the one from Recent Deliveries; `change_status` is `new` / `existing` / `fixed` |
| Job lifecycle | `review_runs` row goes `pending` → `running` → `completed`/`partial`/`failed`; `head_sha`, `merge_base_sha`, and `analysis_meta` are populated |
| Webhook durability | `webhook_deliveries` row for that delivery is `succeeded` (not `processing`); Redeliver from GitHub shows `duplicate_ignored` |
| Full flow | All of the above lining up for one PR |

**Report back what you actually see at each checkpoint** (paste error
messages, screenshots, or log lines) — that's the fastest way for me to
help you fix whatever comes up, rather than me guessing at infrastructure
I can't reach from here.
