# GitHub App setup — USER ACTION REQUIRED

**Status: not registered.** This environment has no GitHub account access,
so the App described below has not been created. Nothing in this repo
claims otherwise — `/api/github/webhook` will reject every real request
until `GITHUB_WEBHOOK_SECRET` is configured with a value that matches a
real App's webhook secret.

Whoever on the team has admin access to the target GitHub account/org needs
to do the following, exactly once per environment (a "dev" App and a
"production" App are recommended as two separate Apps, so testing never
risks production installations).

## 1. Create the App

GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.

| Field | Value |
|---|---|
| GitHub App name | `Codentry` (or `Codentry Dev` for the dev App) |
| Homepage URL | The Vercel deployment URL, or this repo's URL for now |
| Webhook URL | `https://<your-vercel-domain>/api/github/webhook` |
| Webhook secret | Generate a strong random value (e.g. `openssl rand -hex 32`). Save it — this becomes `GITHUB_WEBHOOK_SECRET`. |
| Setup URL (optional) | `https://<your-vercel-domain>/setup` — GitHub redirects users here after install |

## 2. Permissions — exactly these, nothing more

| Permission | Access |
|---|---|
| Pull requests | Read & write |
| Contents | Read-only |
| Metadata | Read-only (mandatory default, cannot be changed) |

Do **not** grant: Administration, Actions, Checks-write, Workflows, or any
organization-level permission. This isn't just policy — the App is
structurally incapable of merging or approving a PR if the token it can
mint never has that scope in the first place, regardless of what any AI
layer's output says (see the security note in Phase 2's final report).

## 3. Subscribe to exactly these webhook events

- `Pull request`
- `Installation`
- `Installation repositories`

Do not subscribe to anything else — GitHub will still send a `ping` event
once on setup regardless (handled explicitly, see `route.ts`), and every
`pull_request` *action* (opened, closed, labeled, etc.) arrives under the
same `Pull request` subscription; Codentry filters to opened/synchronize/
reopened itself in `app/events.py`, not via GitHub's subscription UI (GitHub
doesn't support filtering by action at the subscription level).

## 4. Generate and download the private key

App settings → "Private keys" → "Generate a private key". Downloads a
`.pem` file. This becomes `GITHUB_PRIVATE_KEY` — see `.env.example` for how
to format it as a single-line env var value.

**Handle this file like a password.** Delete the local copy once it's in
your secret manager / platform env vars. Never commit it.

## 5. Where to install it

Install the App on a **test repository first** — not a real team project —
until Phase 2's staging test (`docs/staging-test-phase2.md`) has been run
successfully at least once.

## 6. Populate environment variables

Once the App exists, fill in on the deployed Vercel project:

- `GITHUB_WEBHOOK_SECRET` — from step 1
- `CODENTRY_INTERNAL_WEBHOOK_SECRET` — a separate random value you generate yourself (not from GitHub)
- `NEXT_PUBLIC_API_BASE_URL` — the Render service URL

And on the deployed Render service:

- `CODENTRY_INTERNAL_WEBHOOK_SECRET` — the **same** value as on Vercel
- `GITHUB_APP_ID` — from the App's settings page
- `GITHUB_PRIVATE_KEY` — from step 4
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` — once a Supabase project exists, see `supabase/README.md`

See `docs/deployment.md` for the platform-level deployment steps this
depends on.
