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
  service on the **Docker runtime** (`services/ai-review/Dockerfile`, build
  context `services/ai-review`).
- **Manual**: create a new Web Service with runtime **Docker**, Dockerfile path
  `./services/ai-review/Dockerfile`, Docker build context directory
  `./services/ai-review`, health check path `/health`. No build or start command
  is needed; the image's last stage starts `uvicorn` on `$PORT`.

**Why Docker.** ESLint needs Node.js and Semgrep needs Python, and Render's
native Python runtime was never confirmed to ship `node`. The image contains
both (Python 3.13 + the `node` binary + the pinned ESLint baseline installed
with `npm ci`), runs as a non-root user (uid 10001), and keeps the application
tree read-only for that user.

**Status of the image (see `docs/PROJECT_STATUS.md`):** IMPLEMENTED, VERIFIED
LOCALLY on Docker Desktop (Linux engine): the production image builds; the
analysis CLI runs inside it with `--network none --read-only` and reports
`completed` with 5 findings; the service test suite passes inside the `test`
target (401 passed, 1 deselected — see the comment in the Dockerfile for why);
a production-mode start without secrets refuses to start. **NOT VERIFIED ON
RENDER**: no Render build has ever run, so the build time, image pull and
cold-start numbers on Render are unknown.

**Free-tier CPU risk (local proxy, not a Render measurement).** The same CLI
run, repeated with Docker CPU limits, was `completed` down to 0.25 CPU (34 s)
but `partial_failure` at 0.1 CPU (67 s): Semgrep exceeded the service's 30 s
Semgrep timeout, so 2 of 5 findings were produced. Render's free instances get
a small fraction of a CPU, so expect `partial` runs there until measured; the
first real deploy should record the actual Semgrep duration.

Local commands (run from `services/ai-review`):

```
docker build -t codentry-ai-review .                      # production image
docker build --target test -t codentry-ai-review:test .   # image that can run pytest
docker run --rm codentry-ai-review:test                   # service test suite
docker run --rm --network none --read-only --tmpfs /tmp \
  codentry-ai-review python -m analysis.run analysis/fixtures eslint_sample.js semgrep_sample.js
```

If either tool is unavailable at run time the review is recorded as `partial`
(`analysis/static_analysis.py`), not a crash.

Environment variables to set in the Render dashboard (not in `render.yaml`,
so they're never committed):

- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`
- `CODENTRY_INTERNAL_WEBHOOK_SECRET` — must exactly match the value set on Vercel.
- `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY` — see `docs/github-app-setup.md`.
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — see `supabase/README.md`.
  **Required.** With `ENVIRONMENT=production` (or anything other than
  `development`/`test`, including a typo) the service **refuses to start**
  without these and without `CODENTRY_INTERNAL_WEBHOOK_SECRET`. The in-memory
  store exists only for local development and tests (Phase 0 changed this from
  a warn-and-continue fallback that silently lost every event and job on
  restart).
- Optional worker tuning: `WORKER_ENABLED` (default `true`),
  `WORKER_POLL_SECONDS` (`2.0`), `JOB_LEASE_SECONDS` (`600`),
  `JOB_MAX_ATTEMPTS` (`3`).
- `CLAUDE_API_KEY` — leave unset. There is no AI review in this codebase.

The review worker is a single thread inside this web process. Render's free
tier spins the process down when idle, so a job enqueued just before sleep waits
for the next wake-up (the job is a database row and survives), and
GitHub events that arrive while the service is asleep are the "Vercel-side inbox
gap" described in `docs/architecture.md` (known gap #1).

Also set on **Vercel** (`apps/web`) only if you want the internal debug page:

- `INTERNAL_PAGES_ENABLED=true`, `INTERNAL_PAGES_USER`, `INTERNAL_PAGES_PASSWORD`.
  Without `INTERNAL_PAGES_ENABLED=true` the page is a 404. With it enabled but
  the credentials unset it is a 503 (fails closed). Use a long random password;
  this is HTTP Basic auth, adequate for a team-only debug view and nothing more.

Note: Render's free tier spins down an idle service. The first request after
idling will be slow (cold start). This is measured properly in Phase 7, not
worked around here.

## Supabase

See `supabase/README.md` — project creation and migration application are
manual steps, not part of this deployment doc. Four migrations exist so
far: `0001_enable_pgvector.sql`, `0002_github_app_bookkeeping.sql`,
`0003_findings.sql`, and `0004_durable_events_and_jobs.sql`; apply all four, in
order. **`0004` is required by the Phase 0 code** — without it the durable
delivery/job columns do not exist and the store will error. It has not been
run against a live database here.

## GitHub App

See `docs/github-app-setup.md` (marked USER ACTION REQUIRED — not created in
this environment) and `docs/staging-test-phase2.md` for the manual
verification procedure once everything above is deployed.
