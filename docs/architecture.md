# Architecture (as of Phase 0: foundation hardening)

This document describes what the repository **actually does today**. Where it
differs from the original PRD or the README's product vision, this document is
the one to trust. Anything not built is listed under
[What does not exist](#what-does-not-exist).

## What Codentry is — and is not

**Is:** an evidence-first GitHub pull-request analysis system. It compares the
pull request's head against its merge base with deterministic static analysis
(ESLint + a small hand-written Semgrep ruleset) and works out which findings the
change *introduces*. Its long-term purpose is to *measure* the accuracy,
overlap, and noise of each review signal
([`research-design.md`](research-design.md)).

**Is not (yet):**

- an AI code reviewer — there is no Claude/LLM code anywhere in this repository;
- a comment-posting bot — nothing is written to GitHub except the
  installation-token exchange (`tests/test_scope_guards.py` enforces this);
- a dashboard, billing system, RAG system, or multi-agent system;
- related to CodeArena, coding assessments, judges, or trainers. Those are a
  different product. The boundary is enforced by a repository check in
  `tests/test_scope_guards.py`, and nothing under `apps/`, `services/`,
  `packages/`, or `supabase/` implements any of them.

**Current phase:** Phase 0 — foundation hardening plus deterministic analysis.
AI review is a future phase, gated on an evaluation harness existing first.

## Component flow

```
GitHub ──webhook──▶ apps/web (Vercel)                       services/ai-review (Render)
                    /api/github/webhook                     ─────────────────────────────
                    ├ raw-body HMAC-SHA256 verify           POST /internal/webhook/pull-request
                    ├ ping / event allowlist                ├ X-Codentry-Internal-Secret check
                    ├ per-instance rate limit               ├ claim_delivery  ─▶ webhook_deliveries
                    └ forward (4s timeout, 1 retry) ───────▶│   (processing, payload stored)
                       honest 502 if backend is down        ├ process_event: idempotent bookkeeping
                                                            │   installations/repositories/pull_requests
                                                            │   + enqueue_review_run (unique per PR+head SHA)
                                                            └ mark_delivery(succeeded) ── only now
                                                                          │
                                                   review_runs (pending) ─┘   ◀── the job queue
                                                                          │
                                                        ReviewWorker (1 thread, polls the DB)
                                                        ├ claim_next_review_run  (compare-and-swap + lease)
                                                        ├ fetch PINNED snapshot from GitHub (paginated)
                                                        ├ analyze merge-base and head (same tools, same rules)
                                                        ├ classify: new / existing (moved?) / fixed
                                                        └ finalize (fenced by attempts) ─▶ findings + status
```

## Trust boundaries

Everything that comes from a pull request is hostile input: file paths, file
contents, and any configuration file it ships.

| Boundary | Rule | Where |
|---|---|---|
| PR → analysis tools | No PR-supplied config is ever loaded. ESLint config = Codentry baseline + an optional **sanitized** overlay from the trusted **base** commit (`rules`/`env`/`globals` only) | `analysis/trusted_config.py` |
| PR → subprocess env | Explicit allowlist; server secrets never reach ESLint/Semgrep; temp `HOME`/`TEMP`; `NODE_OPTIONS` pinned | `analysis/subprocess_env.py` |
| PR paths → argv | `./`-prefixed, after `--`; paths validated (no absolute/drive/UNC/`..`/backslash/colon/control chars/reserved names) | `analysis/workspace.py`, runners |
| PR → its own review | Inline `eslint-disable`/`nosemgrep`, `.eslintignore`, `.semgrepignore` are ignored or never written | runner flags, `is_control_file` |
| Tool output → storage | Best-effort secret redaction of finding text and tool error snippets | `analysis/redact.py` |
| Vercel → Render | Shared secret in `X-Codentry-Internal-Secret`, distinct from GitHub's webhook secret; fail-closed if unset | `app/internal_auth.py` |
| Internet → internal pages | `/internal/*` is 404 unless `INTERNAL_PAGES_ENABLED=true`, then HTTP Basic auth | `apps/web/middleware.ts` |
| Public surfaces | `/api/status` and the home page report only `ok`/`unreachable`; `/health` reveals no configuration; FastAPI `/docs` and OpenAPI are off outside development/test | `apps/web`, `app/main.py` |

## Durable webhook events (`webhook_deliveries`)

```
                  ┌────────────── redelivery / sweeper reclaim ──────────────┐
                  ▼                                                          │
 (new) ─▶ processing ──all side effects committed──▶ succeeded  (only this is a duplicate)
              │
              ├── EventPayloadError ──▶ failed      (bad input; a manual redelivery can retry)
              └── any other error ────▶ retryable   (transient)
   crashed before marking ─▶ stays `processing`; reclaimed after the 120s lease
```

`received` exists in the DB vocabulary but is collapsed into `processing`: the
bookkeeping runs inside the request that receives the event, so there is no
"stored but not started" state. The payload is stored with the row, so a sweeper
(inside the worker loop, every 30s) can reprocess it without GitHub.
`process_event` is idempotent (upserts + an enqueue keyed on
`(pull_request, head_sha)`), so reprocessing cannot create a second review.
After 5 attempts a delivery is marked `failed` permanently.

**Fixed defect:** Phase 3 recorded the delivery id *before* processing, so a
failure followed by a retry or a GitHub "Redeliver" was treated as a duplicate
and the event was silently lost.

## Durable review jobs (`review_runs`)

```
 pending ──claim──▶ running ──▶ completed | partial | failed
    │                 │  ▲
    │                 │  └── lease expired (worker died) / transient error ── back to pending
    │                 └────▶ superseded            (head moved / repo deactivated)
    └──────────────────────▶ superseded            (a newer head commit arrived)
 failed ──manual POST /internal/review-runs/{id}/retry──▶ pending
```

- **The row is the job.** No new infrastructure: one in-process worker thread
  polls `review_runs`. A process restart loses nothing; the row is reclaimed
  when its lease expires.
- **Claim** is a compare-and-swap on `(status, attempts)`; **`attempts` is a
  fencing token** — a worker that lost its lease finalizes to nothing.
- **Lease** = `available_at` on a running job (600s, extended at phase
  boundaries). For a pending job `available_at` is the not-before time
  (exponential backoff 30s → 900s, honoring `Retry-After`).
- **Bounded:** 3 attempts, then `failed` — never `running` forever
  (`tests/test_store_state_machines.py::test_no_job_is_ever_left_running_forever_by_a_dead_worker`).
- **Idempotent enqueue:** unique `(pull_request_id, head_sha)`. Redelivering or
  reopening at the same commit does not create a second review.
- **Deterministic superseding:** a run is reportable only if its `head_sha` is
  still the PR head at (1) claim, (2) the start of the GitHub fetch, (3) the end
  of the fetch, and (4) just before finalize. Any mismatch → `superseded`.
  Older *pending* runs are superseded when a newer head is enqueued.
- **Out-of-order events:** `pull_requests.github_updated_at` prevents an older
  event delivered late from rewinding the stored head.

`completed` means every tool ran, nothing that should have been analyzed was
skipped, and the differential covered every file. Otherwise the run is
`partial` with reasons in `analysis_meta.incomplete_reasons` (Phase 3 mapped a
one-tool failure to `completed`; that hid the loss).

## Pinned, complete PR snapshot (`analysis/changed_files.py`)

Every content read is `?ref=<sha>` (head SHA for new code, **merge base** for
old code, event **base** SHA for trusted config). The changed-file list follows
`Link: rel="next"` and is checked against the API's own `changed_files` count.
More than 200 analyzable files → the run **fails** with `too_many_files`
instead of silently reviewing a prefix. Symlinks, submodules, oversized,
non-UTF-8 files, and blob-SHA mismatches are recorded as skips. Errors are
classified retryable (5xx, network, rate limit) or permanent (404, auth).

## Differential analysis (`analysis/differential.py`)

The pure orchestration (analyze base and head, classify, decide `completed`/`partial`/`failed`, build `analysis_meta`) lives in `analysis/snapshot_analysis.py`; `app/review_runner.py` only supplies the identity scope and the fetched snapshot, and the evaluation harness calls the same function, so measurements and production run one code path.

The same tools and rules run on the merge base and the head. Head findings are
matched to base findings by **identity**, not line:

`identity_key = sha256(repo | source | head-path | rule | normalized message | normalized anchor text)`,
`dedup_hash = sha256(identity_key | occurrence index)`.

Inserting code above a finding does not change its identity; editing the flagged
line does; whitespace changes do not; a rename keeps identity through the rename
map. Classification: `new`, `existing` (`moved` if the flagged code sits on a
PR-added line), `fixed`. Findings that cannot be honestly classified (a tool
failed on the base, or the file's old content was unreadable) stay
`change_status = NULL` and are **never** treated as new. Only `new` findings are
ever candidates for reporting in a later phase.

## Fail-closed configuration

Any `ENVIRONMENT` other than `development`/`test` (including typos) requires
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and
`CODENTRY_INTERNAL_WEBHOOK_SECRET`; otherwise the service **refuses to start**.
The in-memory store exists only for development and tests.

## What does not exist

No Anthropic/OpenAI/Gemini SDK, prompt builder, AI validator, AI finding, model
router, RAG, multi-agent code, AI confidence scores, dashboard, billing, or
comment posting. `Finding.source` allows `"AI"` only because the schema contract
anticipates it; nothing constructs one (`tests/test_scope_guards.py`).
`evaluation/` holds only the offline evaluation harness (case format, Arm A runner, matching, statistics, dataset importers with 237 cases, labeling tools): no AI arm and no results. It imports `analysis/` and nothing from `app/`, and production code never imports it (`tests/test_scope_guards.py`).

## Known remaining gaps (read before trusting this)

1. **Vercel-side webhook inbox does not exist.** Durability starts when an event
   *reaches* `services/ai-review`. If Render is unreachable when GitHub's webhook
   arrives (cold start, outage), `apps/web` retries once, returns 502, and the
   event is stored nowhere Codentry controls. Recovery is a manual GitHub
   "Redeliver". Closing this needs an insert-only inbox on the Vercel side with
   HMAC re-verification on pickup; it is the next architectural step, not done.
2. **Not a sandbox.** Subprocesses get a scrubbed env, a temp HOME, resource
   flags, and are killed on timeout — but there is no container, seccomp, or
   network namespace. A tool vulnerability that escapes ESLint/Semgrep parsing
   could still touch the host filesystem and network. Mitigation is
   defense-in-depth, not isolation. Run under an unprivileged user in a
   throwaway container in any real deployment.
3. **`SupabaseReviewStore` has never run against a live Postgres.** Claim and
   finalize race-safety are by construction (conditional updates); they are
   proven only for the in-memory store. `finalize` is four PostgREST calls, not
   one transaction; a lease expiring mid-finalize is handled (the newer attempt
   replaces the findings) but is not proven against a live database.
4. **Real GitHub end-to-end has not been run.** No GitHub App, Supabase project,
   Render service, or Vercel deployment exists in this environment. The
   verification here is a local, mocked-GitHub run with real ESLint/Semgrep
   (`tests/test_e2e_local_mocked.py`) — **not** real GitHub verification.
5. **The Semgrep arm is six hand-written rules**, not Semgrep's registry
   coverage (`analysis/semgrep-rules/README.md`). Never report it as "Semgrep's
   accuracy".
6. **Secret redaction is pattern-based** and will miss bespoke token formats.
7. **A single worker thread** processes one PR at a time; a large PR delays
   others. On a host that sleeps when idle the worker sleeps too.
8. **Free-tier CPU/memory/cold-start behavior is unmeasured.**
9. **POSIX-only PoC** (`--parser=./evil.js` smuggled through a directory named
   `--parser=.`) cannot run on Windows; it is exercised by CI on Ubuntu, which
   has not run yet.
