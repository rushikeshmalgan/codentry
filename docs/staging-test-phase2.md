# Phase 2/3 staging test procedure — USER ACTION REQUIRED

Updated for Phase 3: step A.5/A.6 below now also cover verifying real
ESLint/Semgrep findings were persisted, not just an empty completed run.

**Status: BLOCKED in this environment.** These procedures need a registered
GitHub App (`docs/github-app-setup.md`), a deployed Vercel + Render pair
(`docs/deployment.md`), and a provisioned Supabase project
(`supabase/README.md`) — none of which exist here. What follows is the
exact procedure to run once someone with those accounts has completed
setup; it is not something this environment can execute or fabricate
results for.

What Phase 2 *has* been verified against, in lieu of the above: a full
local end-to-end run (real HMAC signatures, both services actually running,
real HTTP hops) using the in-memory store fallback — see the Phase 2 final
report's "Staging test results" section for those actual numbers. The
procedures below are the remaining gap between that and a genuine staging
environment.

## A. End-to-end staging test

1. Install the Codentry GitHub App (dev variant) on a disposable test
   repository.
2. Open a pull request on that repository.
3. In the GitHub App's settings → Advanced → Recent Deliveries, confirm a
   `pull_request` delivery shows a **green 202** response, delivered in
   well under 10 seconds.
4. In Render's logs for `codentry-ai-review`, confirm a
   `pull_request_event_accepted` log line with a `review_run_id`.
5. Query `GET /internal/review-runs/{id}` (with the internal secret header)
   and confirm `status` leaves `pending` (the worker picks it up within a few
   seconds) and reaches `completed` (or `partial`/`failed`, with a specific
   `error_code`/`error_message` — see `docs/static-analysis.md`'s
   failure-behavior section — if the App's Node/Semgrep setup on Render isn't
   working yet), with `latency_ms`, `head_sha`, `merge_base_sha`, and
   `analysis_meta` populated. (Phase 0: the webhook no longer runs the review
   inline; a durable worker does.)
6. Confirm in the Supabase table editor that `installations`,
   `repositories`, `pull_requests`, `review_runs`, **and `findings`** rows
   exist and match what GitHub sent — if the test PR has any real ESLint or
   Semgrep violations, they should appear here with `source` correctly set
   to `ESLINT` or `SEMGREP`.
7. Confirm **no comment was posted to the PR** — Phase 3 only persists
   findings to the database; posting them is Phase 5. This absence is
   itself part of the pass criteria.

## B. GitHub "Redeliver" test (replay protection)

1. From the same Recent Deliveries screen, pick the `pull_request` delivery
   from step A.3 and click **Redeliver**.
2. Confirm Render's logs show `webhook_delivery_duplicate` for that
   delivery id, and the response is still 202 (not an error — a duplicate
   is a successfully handled outcome, not a failure).
3. Confirm no second row was added to `review_runs` for that PR.
4. Also confirm the `webhook_deliveries` row for that delivery has
   `status = succeeded`. (Phase 0: only a *succeeded* delivery is a duplicate;
   a delivery that failed earlier is reprocessed on redelivery, not ignored.)
5. Record the result here (date, who ran it, pass/fail) once done.

## C. Uninstall test

1. From the repository (or the App's settings), remove the repository from
   the installation, or uninstall the App entirely.
2. Confirm GitHub sends an `installation_repositories` (action: removed) or
   `installation` (action: deleted) event, and Render's logs show it was
   processed.
3. In Supabase, confirm the affected `repositories` row(s) now have
   `is_active = false` — and confirm the `installations` row and all prior
   `pull_requests` / `review_runs` rows for that repository **still exist**.
   Uninstalling must never delete history.
4. Open a new PR against that (now-inactive) repository via the API
   directly, or reinstall briefly to trigger a `synchronize` — confirm the
   resulting webhook is acknowledged (202) but produces
   `"status": "ignored", "reason": "repository_inactive"` with no new
   `review_runs` row.

## Recording results

| Test | Date | Run by | Result |
|---|---|---|---|
| A. End-to-end staging | — | — | not yet run |
| B. Redelivery / replay | — | — | not yet run |
| C. Uninstall | — | — | not yet run |

Update this table in place once each test has actually been run against a
real deployment — do not mark a row passed based on the local E2E test in
the Phase 2 report; that covers different ground (real HTTP + HMAC, but not
real GitHub infrastructure, real Supabase, or real Render cold starts).
