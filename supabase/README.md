# supabase/

This directory holds Codentry's database migrations. It does **not**
provision a Supabase project for you — that's a manual, account-specific
step with no credentials this repository can assume exist.

## One-time setup (per environment: dev / staging / production)

1. Create a project at [supabase.com](https://supabase.com) (free tier is
   sufficient for Phase 1–8).
2. Copy the project's URL and keys into your `.env`:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (backend/`services/ai-review` only — never
     ship this to `apps/web`'s client bundle)
   - `SUPABASE_ANON_KEY` (if `apps/web` ever needs client-side read access)
3. Apply the migrations in `migrations/`, in order, either:
   - by pasting each file's contents into the Supabase SQL editor, or
   - via the Supabase CLI once it's installed and linked:
     `supabase link --project-ref <ref>` then `supabase db push`.

## Current migrations

- `0001_enable_pgvector.sql` — enables the `vector` extension. Enabled from
  Phase 1 onward (even though nothing uses it until Phase 9) specifically so
  turning it on later isn't a surprise migration.

## What's intentionally not here yet

Product tables (`installations`, `repositories`, `pull_requests`,
`review_runs`, `findings`) are introduced in Phase 2, once the GitHub App
integration actually needs somewhere to write to. RAG tables
(`repository_chunks`, `embeddings`, `import_graph_edges`) and evaluation
tables (`evaluation_cases`, `evaluation_runs`) follow in Phases 9 and 10
respectively.
