-- Phase 2: GitHub App integration bookkeeping.
--
-- Adds installations, repositories, pull_requests, review_runs, and
-- webhook_deliveries. No RAG (repository_chunks/embeddings), evaluation, or
-- AI-finding tables here — those arrive in Phases 9-10 and Phase 3-4
-- respectively.

create table if not exists installations (
    id uuid primary key default gen_random_uuid(),
    github_installation_id bigint not null,
    -- Nullable: the pull_request webhook payload only ever carries
    -- installation.id (no account details), so a row can legitimately exist
    -- here before the full `installation` event has ever been seen. It gets
    -- backfilled once that event arrives. See app/store.py upsert_installation.
    account_login text,
    account_type text,
    created_at timestamptz not null default now(),
    constraint installations_github_installation_id_key unique (github_installation_id)
);

create table if not exists repositories (
    id uuid primary key default gen_random_uuid(),
    installation_id uuid not null references installations(id),
    github_repo_id bigint not null,
    full_name text not null,
    -- Nullable for the same reason: installation.created's repositories[]
    -- entries don't include default_branch, only pull_request's repository
    -- object does. Backfilled on the next pull_request event.
    default_branch text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint repositories_github_repo_id_key unique (github_repo_id)
);

create index if not exists repositories_installation_id_idx on repositories (installation_id);

create table if not exists pull_requests (
    id uuid primary key default gen_random_uuid(),
    repository_id uuid not null references repositories(id),
    github_pr_number integer not null,
    title text,
    author_login text,
    head_sha text,
    base_sha text,
    state text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint pull_requests_repository_pr_number_key unique (repository_id, github_pr_number)
);

create index if not exists pull_requests_repository_id_idx on pull_requests (repository_id);

create table if not exists review_runs (
    id uuid primary key default gen_random_uuid(),
    pull_request_id uuid not null references pull_requests(id),
    trigger_event text not null,
    status text not null default 'pending'
        constraint review_runs_status_check
        check (status in ('pending', 'running', 'completed', 'failed')),
    started_at timestamptz,
    completed_at timestamptz,
    latency_ms integer,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists review_runs_pull_request_status_idx on review_runs (pull_request_id, status);

-- Durable replay protection. GitHub delivery IDs are UUIDs and effectively
-- globally unique, so the unique constraint alone is what actually prevents
-- duplicate processing; expires_at is reserved for a future cleanup job and
-- is NOT consulted by the Phase 2 dedup check (an un-pruned row is the safe
-- direction to fail in — it just keeps blocking that same delivery id).
-- A 24h TTL comfortably covers manual GitHub "Redeliver" testing during
-- development without keeping the table growing forever once pruning exists.
create table if not exists webhook_deliveries (
    id uuid primary key default gen_random_uuid(),
    delivery_id text not null,
    event_type text not null,
    received_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    constraint webhook_deliveries_delivery_id_key unique (delivery_id)
);
