-- Close the Supabase Data API to the anon / authenticated roles.
--
-- Migrations 0001-0004 left row level security OFF on every Codentry table, and the
-- anon role kept the default table privileges. Measured on the local Supabase stack
-- (docs/store-contract-tests.md): with only the project's anon key, which Supabase
-- treats as public, a caller could read webhook payloads and installations, and
-- insert, update and delete rows, including a `retryable` webhook_deliveries row that
-- the backend sweeper would then process without any HMAC or internal-secret check.
--
-- The backend uses the service_role key, which bypasses RLS and keeps its grants, so
-- nothing changes for services/ai-review (all store contract tests pass with this
-- migration applied). Nothing else in Codentry talks to Supabase.
--
-- Rule from here on: every new table enables RLS in the migration that creates it
-- (services/ai-review/tests/test_migrations_rls.py enforces it). A future insert-only
-- webhook inbox gets its own table with an explicit INSERT grant and policy; it never
-- reopens these tables.

alter table installations      enable row level security;
alter table repositories       enable row level security;
alter table pull_requests      enable row level security;
alter table review_runs        enable row level security;
alter table webhook_deliveries enable row level security;
alter table findings           enable row level security;

-- No policies are defined, so RLS alone already denies every row to anon and
-- authenticated. Revoking the table privileges as well turns their requests into an
-- explicit permission error (HTTP 401) instead of an empty result.
revoke all on table installations, repositories, pull_requests, review_runs,
    webhook_deliveries, findings from anon, authenticated;
