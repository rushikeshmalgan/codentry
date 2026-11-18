# Store contract tests against a real Postgres

`services/ai-review` has two implementations of one store contract: `InMemoryReviewStore`
(tests, local development) and `SupabaseReviewStore` (production, PostgREST via
`supabase-py`). Until this suite existed, the Supabase one had never run against a
database; its race-safety was "by construction".

`tests/test_store_state_machines.py` now runs every test against **both** stores. The
Supabase variant uses a **local** Supabase stack: Postgres 17 with
`supabase/migrations/0001-0004` applied, PostgREST, the API gateway and the auth service
(needed only so the CLI issues the anon/service_role keys a hosted project has).

## Running it

Needs Docker and Node (for `npx`). From the repository root:

```
npx --yes supabase@2.122.1 start                      # first run pulls images (several minutes)
services/ai-review/scripts/run_store_contract_tests.sh  # PYTHON=... to pick an interpreter
npx --yes supabase@2.122.1 stop --no-backup            # when done
```

The script reads the stack's URL and local keys from `supabase status` and passes them only
to pytest; nothing is printed or written to disk. In a plain `pytest` run (and in the
`ai-review` CI job) the `[supabase]` variants are reported as **skipped** with the reason;
the `store-contract` CI job runs them.

`npx --yes supabase@2.122.1 db reset` re-applies the migrations from scratch.

## Safety

The Supabase variant deletes every row of the Codentry tables before each test, so
`tests/store_backends.py`:

- reads only `CODENTRY_TEST_SUPABASE_URL`, `CODENTRY_TEST_SUPABASE_SERVICE_ROLE_KEY` and
  `CODENTRY_TEST_SUPABASE_ANON_KEY`, never the service's `SUPABASE_URL` /
  `SUPABASE_SERVICE_ROLE_KEY`, so a production configuration is never picked up;
- refuses any URL whose host is not loopback (`UnsafeTestDatabaseError`).

## What it found (first run, 18 November 2026)

| Result | Status |
|---|---|
| Migrations 0001-0004 apply cleanly to a fresh Postgres 17 (Supabase image `17.11.0.006`), three times from an empty volume | VERIFIED LOCALLY |
| All 35 state-machine tests pass on the Supabase backend (79 passed across both backends, including new tests) | VERIFIED LOCALLY |
| The two 8-thread race tests (one delivery owner; one job owner) pass on real Postgres, 5 of 5 repeated rounds | VERIFIED LOCALLY: evidence, not proof (one host, low latency) |
| **Defect:** a lookup by an id that is not a UUID (e.g. `/internal/review-runs/no-such-run`) raised `APIError 22P02` on Postgres, where the in-memory store returns "not found"; the routes would have answered 500 instead of 404 | FIXED (`app/store.py::_is_row_id`) with a test on both backends |
| **Open gap:** row level security is off on all six tables and the `anon` role holds table privileges; with only the anon key a caller could read webhook payloads and insert, update and delete rows, including a `webhook_deliveries` row the sweeper would process | MEASURED LOCALLY; documented by `tests/test_data_api_exposure.py` (strict xfail); fix proposed, **not applied** (docs/architecture.md gap #10) |

A proposed lockdown (enable RLS on all six tables, revoke anon/authenticated privileges)
was applied to the local stack only, to measure it: every anon request became 401, the
service-role store still passed all 79 tests, and the strict-xfail tests turned into
failures as designed. The database was then reset to 0001-0004.

## What this does not cover

- A **hosted** Supabase project (network latency, its PostgREST version, its defaults):
  NOT VERIFIED IN PRODUCTION.
- `finalize_review_run` is still four PostgREST calls, not one transaction; the tests
  cover the fenced outcomes, not every interleaving of a crash between those calls.
- Only `test_store_state_machines.py` is dual-backend. The worker, review-runner and
  endpoint tests still use the in-memory store.
