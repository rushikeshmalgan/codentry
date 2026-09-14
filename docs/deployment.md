# Deployment (Phase 1 baseline)

Both platforms require a dashboard account this repository has no
credentials for, so provisioning is a manual, one-time step per environment
rather than something automated here.

## Vercel — apps/web

1. Import the GitHub repo into a new Vercel project.
2. Set **Root Directory** to `apps/web` (required — this is a monorepo).
3. Framework preset: Next.js (auto-detected once the root directory is set).
4. Environment variables (Project Settings → Environment Variables):
   - `NEXT_PUBLIC_API_BASE_URL` = the deployed Render service URL (e.g.
     `https://codentry-ai-review.onrender.com`).
   - `GITHUB_WEBHOOK_SECRET` — see `docs/github-app-setup.md`.
   - `CODENTRY_INTERNAL_WEBHOOK_SECRET` — a value you generate yourself;
     must exactly match the same variable on Render.
5. Deploy. `/` should render the status page; `/api/status` should report
   `backend: "ok"` once Render is also deployed. `/api/github/webhook`
   should return 503 until `GITHUB_WEBHOOK_SECRET` is set, then 401 for any
   unsigned request — never 501 (that was the Phase 1 stub).

## Render — services/ai-review

Two options:

- **Blueprint**: use Render's "New Blueprint Instance", pointed at this
  repo's `render.yaml`. Render will create the `codentry-ai-review` web
  service with the build/start commands already filled in.
- **Manual**: create a new Web Service, root directory `services/ai-review`,
  runtime Python 3, build command `pip install -r requirements.txt`, start
  command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check
  path `/health`.

Environment variables to set in the Render dashboard (not in `render.yaml`,
so they're never committed):

- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`
- `CODENTRY_INTERNAL_WEBHOOK_SECRET` — must exactly match the value set on Vercel.
- `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY` — see `docs/github-app-setup.md`.
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — see `supabase/README.md`.
  **If these are left unset, the service falls back to an in-memory store**
  (logged loudly at startup as a warning) — every review run and
  installation record is lost on every restart/deploy. Fine for a first
  smoke test, not acceptable for anything real.
- `CLAUDE_API_KEY` — leave unset until Phase 4.

Note: Render's free tier spins down an idle service. The first request after
idling will be slow (cold start). This is measured properly in Phase 7, not
worked around here.

## Supabase

See `supabase/README.md` — project creation and migration application are
manual steps, not part of this deployment doc. Two migrations exist so far:
`0001_enable_pgvector.sql` and `0002_github_app_bookkeeping.sql`; apply both,
in order.

## GitHub App

See `docs/github-app-setup.md` (marked USER ACTION REQUIRED — not created in
this environment) and `docs/staging-test-phase2.md` for the manual
verification procedure once everything above is deployed.
