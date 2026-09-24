-- Phase 3: the findings table. Static findings (source IN ('ESLINT',
-- 'SEMGREP')) are just rows here — no separate per-tool table, per the
-- Phase 3 spec's explicit "do not create separate database schemas for
-- ESLint and Semgrep." AI findings (source = 'AI') reuse this same table
-- from Phase 4 onward.
--
-- dedup_hash is deliberately NOT unique-constrained here: the same
-- underlying issue is expected to legitimately reappear across multiple
-- review_runs for the same PR (e.g. an unfixed issue still present on the
-- next `synchronize`). Dedup-before-posting is a Phase 5 concern, once
-- there's a PR comment to avoid re-posting; Phase 3 just needs the hash
-- computed correctly and stored, which the two required indexes support.

create table if not exists findings (
    id uuid primary key default gen_random_uuid(),
    review_run_id uuid not null references review_runs(id),
    source text not null
        constraint findings_source_check
        check (source in ('ESLINT', 'SEMGREP', 'AI')),
    category text not null
        constraint findings_category_check
        check (category in (
            'correctness', 'security', 'logic', 'cross_file',
            'architecture', 'performance', 'style'
        )),
    severity text not null
        constraint findings_severity_check
        check (severity in ('critical', 'high', 'medium', 'low', 'info')),
    confidence real,
    title text not null,
    description text not null,
    file_path text not null,
    start_line integer not null,
    end_line integer not null,
    suggestion text,
    reasoning text,
    evidence_span text,
    github_comment_id bigint,
    dedup_hash text not null,
    created_at timestamptz not null default now()
);

create index if not exists findings_review_run_source_idx on findings (review_run_id, source);
create index if not exists findings_dedup_hash_idx on findings (dedup_hash);
