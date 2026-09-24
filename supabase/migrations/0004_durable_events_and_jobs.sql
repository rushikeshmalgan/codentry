-- Phase 0: durable webhook events and durable review jobs.
--
-- Before this migration a webhook delivery was recorded BEFORE it was
-- processed (a crash or a 500 permanently swallowed the event, because the
-- retry looked like a duplicate), and a review was an in-process
-- BackgroundTask (a restart left the run `running` forever). This migration
-- gives both an explicit state machine, stored in Postgres.
--
-- Deliberately no new infrastructure: the review_runs table IS the job
-- queue; a single in-process worker polls it (see app/worker.py).

------------------------------------------------------------------------
-- webhook_deliveries: RECEIVED -> PROCESSING -> SUCCEEDED | FAILED | RETRYABLE
------------------------------------------------------------------------
-- `received` is part of the vocabulary but the current code path collapses
-- it into `processing`: bookkeeping runs inside the request that receives
-- the event, so there is no persisted "stored but not started" state yet.
-- Only `succeeded` means "done, ignore duplicates". Rows that existed before
-- this migration were recorded before processing with no outcome; they
-- default to `succeeded` (the prior, weaker semantics) rather than being
-- silently reprocessed.
alter table webhook_deliveries
    add column if not exists status text not null default 'succeeded',
    add column if not exists attempts integer not null default 1,
    add column if not exists payload jsonb,
    add column if not exists last_error text,
    add column if not exists updated_at timestamptz not null default now();

alter table webhook_deliveries drop constraint if exists webhook_deliveries_status_check;
alter table webhook_deliveries
    add constraint webhook_deliveries_status_check
    check (status in ('received', 'processing', 'succeeded', 'failed', 'retryable'));

create index if not exists webhook_deliveries_status_updated_idx
    on webhook_deliveries (status, updated_at);

------------------------------------------------------------------------
-- pull_requests: stale-event guard
------------------------------------------------------------------------
alter table pull_requests
    add column if not exists github_updated_at timestamptz;

------------------------------------------------------------------------
-- review_runs: the durable job
------------------------------------------------------------------------
-- pending -> running -> completed | partial | failed | superseded
--   running -> pending      lease expired (worker crashed) or retryable error
--   failed  -> pending      explicit manual retry only
-- `available_at` is dual-purpose: for a pending job it is the not-before
-- time (backoff); for a running job it is the lease expiry.
-- `attempts` doubles as a fencing token: finalization only succeeds for the
-- attempt that currently holds the job.
alter table review_runs
    add column if not exists base_sha text,
    add column if not exists head_sha text,
    add column if not exists merge_base_sha text,
    add column if not exists attempts integer not null default 0,
    add column if not exists max_attempts integer not null default 3,
    add column if not exists available_at timestamptz not null default now(),
    add column if not exists analysis_meta jsonb,
    add column if not exists error_code text,
    add column if not exists delivery_id text;

alter table review_runs drop constraint if exists review_runs_status_check;
alter table review_runs
    add constraint review_runs_status_check
    check (status in ('pending', 'running', 'completed', 'partial', 'failed', 'superseded'));

-- One review per (pull request, head commit): makes enqueue idempotent, so a
-- redelivered webhook cannot produce a second review of the same code.
create unique index if not exists review_runs_pr_head_sha_key
    on review_runs (pull_request_id, head_sha)
    where head_sha is not null;

create index if not exists review_runs_claim_idx
    on review_runs (status, available_at);

------------------------------------------------------------------------
-- findings: identity v2 and differential classification
------------------------------------------------------------------------
-- identity_key is content-anchored (no line numbers); dedup_hash is
-- identity_key + occurrence index. change_status is relative to the merge
-- base: new (introduced by the PR), existing (already there), fixed
-- (removed by the PR). NULL means "not classified against a base".
alter table findings
    add column if not exists identity_key text,
    add column if not exists change_status text,
    add column if not exists moved boolean not null default false,
    add column if not exists in_diff boolean not null default false,
    add column if not exists base_start_line integer;

alter table findings drop constraint if exists findings_change_status_check;
alter table findings
    add constraint findings_change_status_check
    check (change_status is null or change_status in ('new', 'existing', 'fixed'));

create index if not exists findings_run_change_status_idx
    on findings (review_run_id, change_status);
create index if not exists findings_identity_key_idx on findings (identity_key);
