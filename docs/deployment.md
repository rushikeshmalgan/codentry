# Deployment (Phase 1 baseline)

Both platforms require a dashboard account this repository has no
credentials for, so provisioning is a manual, one-time step per environment
rather than something automated here.

## Vercel — apps/web

1. Import the GitHub repo into a new Vercel project.
2. Set **Root Directory** to `apps/web` (required — this is a monorepo).
3. Framework preset: Next.js (auto-detected once the root directory is set).
4. Environment variables (Project Settings → Environment Variables):
   - `AI_REVIEW_SERVICE_URL` = the deployed Render service URL (e.g.
     `https://codentry-ai-review.onrender.com`).
5. Deploy. `/` should render the status page; `/api/status` should report
   `backend: "ok"` once Render is also deployed.

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
- Everything else in `.env.example` under "Not used until Phase N" — leave
  unset until the corresponding phase actually reads it.

Note: Render's free tier spins down an idle service. The first request after
idling will be slow (cold start). This is measured properly in Phase 7, not
worked around here.

## Supabase

See `supabase/README.md` — project creation and migration application are
manual steps, not part of this deployment doc.
