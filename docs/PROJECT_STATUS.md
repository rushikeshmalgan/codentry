# Codentry — Current Project Status & Implementation Documentation

**As of:** 24 September 2026, after Phase 0 (foundation hardening) and before any further implementation.
**Audience:** team members, project guides, reviewers, and future developers. Assumes no prior knowledge.
**Source of truth for implemented behavior:** the repository. Where this document and the code disagree, the code wins; please fix the document.

**Companion documents:** [WHAT_CHANGED.md](WHAT_CHANGED.md) · [FINAL_PRODUCT_AND_PRICING.md](FINAL_PRODUCT_AND_PRICING.md) · [NO_COST_ALTERNATIVES.md](NO_COST_ALTERNATIVES.md) · [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md) · [architecture.md](architecture.md) · [research-design.md](research-design.md) · [phase0-hardening-report.md](phase0-hardening-report.md) · [literature-survey-updated-2026-09-24.pdf](literature-survey-updated-2026-09-24.pdf)

Status vocabulary used throughout: **IMPLEMENTED**, **PARTIALLY IMPLEMENTED**, **PLANNED**, **NOT IMPLEMENTED**, **VERIFIED LOCALLY** (an automated test or a manual check passes on a developer machine), **NOT VERIFIED IN PRODUCTION** (never run against real GitHub, Supabase, Render, or Vercel).

---

## 1. Executive summary

Codentry is a GitHub App backend that receives pull-request webhooks, fetches the exact base and head commits of the pull request, runs deterministic static analysis (ESLint and a small Semgrep ruleset) on both, and works out which findings the pull request **introduced**, as opposed to findings that were already in the code. The results are stored in a database.

What exists today is a hardened, tested **static-analysis pipeline** with durable webhook and job handling. What does **not** exist today: any AI/LLM review, any comment posted back to GitHub, any evaluation harness, any dashboard, and any verification against real GitHub, Supabase, Render, or Vercel.

The project's stated research direction is *evidence-first*: an AI reviewer, when added, is one optional signal whose accuracy, overlap with static analysis, and noise are to be measured against defensible ground truth — not assumed to be good.

## 2. What Codentry is

An evidence-first GitHub pull-request analysis system that combines differential static analysis with optional AI review and empirically evaluates the accuracy, overlap, and noise of each review signal.

Today it is only the first part of that sentence (differential static analysis), plus the plumbing to run it reliably.

## 3. The problem it addresses

Reviewing pull requests takes time and context that small teams often lack (see the PRD, `docs/Codentry_PRD.docx`, §2). Automated tools help, but static tools run on whole files report findings in code the change did not write, and the sources reviewed in the updated survey offer limited evidence on how much of what any reviewer — static or AI — reports is *real, new, and actionable* ([survey §11](literature-survey-updated-2026-09-24.pdf)). Codentry's first technical contribution is to separate "introduced by this PR" from "already there" and to make every finding reproducible; its research contribution (not yet executed) is to measure the signals.

## 4. Why ordinary AI code review alone is insufficient for this direction

This is a statement about what *this project* needs, not a claim that AI review is bad. Each point below is grounded in sources checked for the updated survey ([literature-survey-updated-2026-09-24.pdf](literature-survey-updated-2026-09-24.pdf)); numbers in brackets are that survey's reference numbers.

1. **No independent ground truth.** An AI reviewer's own opinion cannot validate itself. Automated evaluation of review bots showed only moderate agreement with developer labels (0.44–0.62 across three LLM judges) [41], and LLM judges show measurable self-preference [43, 44]. Same-model blind spots are reported for self-repair of generated code [45].
2. **Non-determinism.** The same prompt can return different code; a single run is not a reliable measurement [46, 47, 48].
3. **Noise and actionability.** Static analysis has a known false-alarm problem [33, 35], and industrial LLM comments include "faulty reviews, unnecessary corrections, and irrelevant comments" [40]. A system must be able to *count* noise, which requires stable finding identity.
4. **Benchmark contamination.** Public benchmarks may leak into training data [49, 50, 51]; results on public repositories need care.
5. **Untrusted input.** An AI reviewer that reads repository content is a prompt-injection target with elevated permissions [56, 57]; the analysis pipeline itself is an attack surface (Phase 0 fixed several such holes in the *static* pipeline; see §17).
6. **Different signals catch different things.** Comparisons of SAST tools and LLMs report a trade-off (low detection/low false positives for SAST vs. high detection/high false positives for LLMs) and suggest ensembling [36] — a claim Codentry intends to *test*, not assume.

## 5. Current research question

> How do deterministic static analysis and LLM-based review differ in defect coverage and review noise on pull-request changes, and does combining their independent evidence improve useful defect detection without producing unacceptable false positives?

Codentry does **not** claim that LLMs beat static analysis, that static analysis beats LLMs, or that combining them is proven better. See [research-design.md](research-design.md) for arms, ground truth, and metrics.

## 6. Product vision (not the current state)

A GitHub App that, for each pull request, reports only what the change introduced, with the evidence (tool, rule, location) attached, and — later — an optional AI signal whose contribution is measured separately. Full definition, including what is required for an MVP versus the research project versus optional future features: [FINAL_PRODUCT_AND_PRICING.md](FINAL_PRODUCT_AND_PRICING.md).

## 7. Current architecture

```
                         GitHub
                           │  pull_request / installation / installation_repositories
                           ▼   (webhook, HMAC-SHA256)
               ┌───────────────────────────┐
               │ apps/web  (Next.js, Vercel)│   verify raw-body HMAC · ping/event allowlist
               │ /api/github/webhook        │   per-instance rate limit · forward (4s + 1 retry)
               └─────────────┬─────────────┘   honest 502 if backend unreachable
                             │  X-Codentry-Internal-Secret
                             ▼
               ┌──────────────────────────────────────────────────────────┐
               │ services/ai-review  (FastAPI, Render)                    │
               │  POST /internal/webhook/pull-request                     │
               │    claim_delivery → process_event → mark_delivery        │
               │  ReviewWorker (1 thread, polls DB)                       │
               │    claim job → pinned GitHub snapshot → analyze base+head│
               │    → classify new/existing/fixed → fenced finalize       │
               └───────────────┬──────────────────────────────────────────┘
                               │ supabase-py (PostgREST)
                               ▼
                      Supabase Postgres  (migrations 0001–0004)

   analysis/  (standalone package, no app/GitHub/Supabase/AI imports, except changed_files.py)
      workspace → ESLint + Semgrep (scrubbed env) → normalize → identity → differential
```

Nothing in this diagram posts to GitHub except the installation-token exchange. There is no AI component.

## 8. Current technology stack

| Layer | Technology (from the manifests) | Notes |
|---|---|---|
| Frontend / webhook edge | Next.js `^15.0.3`, React `^19.0.0`, TypeScript `^5.6.3`, Vitest `^5.0.0` | [apps/web/package.json](../apps/web/package.json) |
| Backend | Python 3.13 (CI and ruff target), FastAPI `>=0.115`, uvicorn, pydantic-settings, httpx, PyJWT | [requirements.txt](../services/ai-review/requirements.txt) |
| Static analysis | ESLint `^8.57.1` (pinned baseline install), `@typescript-eslint/parser ^7.18.0`, Semgrep `>=1.70` (1.177.0 installed locally) | [eslint-baseline/package.json](../services/ai-review/analysis/eslint-baseline/package.json) |
| Database | Supabase Postgres via `supabase-py >=2.9`; `pgvector` extension enabled by migration 0001 but **unused** | [supabase/migrations/](../supabase/migrations/) |
| Tests / lint | pytest, respx, PyYAML (dev), ruff; Vitest, `next lint`, `tsc` | [requirements-dev.txt](../services/ai-review/requirements-dev.txt) |
| CI | GitHub Actions (ubuntu-latest, Node 22, Python 3.13) | [ci.yml](../.github/workflows/ci.yml) — **has not run on this state of the repo** |
| Hosting (planned, unverified) | Vercel (web), Render (backend), Supabase (DB) | [render.yaml](../render.yaml), [deployment.md](deployment.md) |
| AI | **None** | A `CLAUDE_API_KEY` setting exists but nothing reads it |

## 9. Current repository structure

```
codentry/
├─ apps/web/                     Next.js app: webhook receiver, status route, setup + internal pages
│  ├─ app/api/github/webhook/     public webhook (HMAC verify → forward)
│  ├─ app/api/status/             public liveness (ok / unreachable only)
│  ├─ app/internal/installations/ team-only debug page (gated by middleware.ts)
│  ├─ middleware.ts, lib/         Basic-auth gate, webhook/HMAC, rate limit, internal client
│  └─ tests/                      6 files, 38 tests
├─ services/ai-review/
│  ├─ app/                        FastAPI: config, events, ingest, store, worker, review_runner, routes_internal
│  ├─ analysis/                   standalone analysis package (workspace, runners, identity, diff, differential, …)
│  │  ├─ eslint-baseline/         pinned ESLint + baseline config
│  │  ├─ semgrep-rules/           production.yml (6 rules) + README
│  │  └─ fixtures/                3 JS files used by tests
│  └─ tests/                      34 Python files (incl. helpers)
├─ packages/schemas/              Finding JSON Schema (review.schema.json) + README
├─ supabase/migrations/           0001 … 0004 (+ README)
├─ evaluation/                    README only — no harness yet
├─ docs/                          this document set; PRD (docx); original literature survey (pdf); backup/
├─ render.yaml, .env.example, .github/workflows/ci.yml
└─ README.md
```

## 10. GitHub integration flow

1. The Codentry **GitHub App** (not yet registered — USER ACTION REQUIRED; [github-app-setup.md](github-app-setup.md)) is installed on a repository.
2. GitHub sends `installation`, `installation_repositories`, and `pull_request` webhooks to the Vercel URL.
3. To read code, the backend signs an **App JWT** (RS256) with the private key and exchanges it for a short-lived **installation access token** ([github_auth.py](../services/ai-review/app/github_auth.py)).
4. Requested permissions: Pull requests (read & write), Contents (read-only), Metadata (read-only). Write access is requested for a future comment feature and is **not used today**.
5. GitHub documents that it does not automatically redeliver failed webhook deliveries and expects a 2XX within 10 seconds ([GitHub Docs](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries), checked 2026-09-24). This matters for gap #1 in §29.

## 11. Webhook flow

`apps/web` verifies the HMAC over the **raw body**, checks the event type against an allowlist, applies a per-instance in-memory rate limit, and forwards to the backend with a 4-second timeout and one retry; if the backend is unreachable it answers GitHub **502** rather than pretending success ([route.ts](../apps/web/app/api/github/webhook/route.ts)). The backend authenticates the forward with a separate shared secret. Verified locally by unit tests; not verified with real GitHub signatures.

## 12. Job lifecycle

Two durable state machines (details and diagrams: [architecture.md](architecture.md)):

- **Delivery** (`webhook_deliveries`): `processing → succeeded | failed | retryable`. Only `succeeded` is a duplicate. Payload stored; a sweeper reprocesses stuck deliveries; 5 attempts maximum.
- **Review job** (`review_runs`): `pending → running → completed | partial | failed`, plus `superseded`; `running → pending` on lease expiry or a transient error; `failed → pending` only by manual retry. Unique per `(pull_request, head_sha)`. `attempts` is a fencing token. 3 attempts maximum.

Proven for the **in-memory** store (`tests/test_store_state_machines.py`, 36 tests). The Supabase implementation uses conditional updates for the same contract and has **never run against a live Postgres**.

## 13. Review lifecycle (what happens to one pull request)

1. Webhook accepted → delivery claimed → bookkeeping upserts → job enqueued for `(PR, head SHA)`; a newer head supersedes older *pending* jobs.
2. Worker claims the job (lease 600 s) and re-checks that the head is still current.
3. Snapshot fetched (see "Pinned, complete PR snapshot" in [architecture.md](architecture.md)): pinned to head SHA, merge base, and base SHA; paginated; verified against the API's own file count; head re-checked before and after.
4. Base and head analyzed with identical tools, rules, and trusted configuration.
5. Findings classified and persisted with `analysis_meta` (tool versions, ruleset hash, config source, skip reasons).
6. Finalize is fenced by `attempts`; a run is `completed` only if nothing that should have been analyzed was skipped, otherwise `partial`.
7. **Nothing is posted to the pull request.**

## 14. Static analysis lifecycle

`prepare_files` (drops unsafe paths, control files, non-analyzable types, oversize files — each with a recorded reason) → ephemeral workspace + tool sandbox (temp HOME/TEMP, generated config **outside** the workspace) → ESLint and Semgrep with a scrubbed environment, `--`, `./`-prefixed paths, no inline config, no ignore files, `--disable-nosem`, resource ceilings, process-tree kill on timeout → normalize (secrets redacted) → identity assignment. Config is never taken from the PR: baseline + an optional sanitized overlay from the **base** commit (`rules`/`env`/`globals` only). See [static-analysis.md](static-analysis.md).

## 15. Differential analysis

The same tools run at the merge base and at the head; head findings are matched to base findings by identity and classified `new` (introduced by the PR), `existing` (already present; `moved=true` only if the flagged code sits on a PR-added line), or `fixed` (removed by the PR). Findings that cannot be honestly classified (a tool failed on the base, or old content was unreadable) stay `change_status = NULL` and are never treated as new. Implemented in [differential.py](../services/ai-review/analysis/differential.py); verified locally with real ESLint/Semgrep on in-memory content; **not** verified on real pull requests.

## 16. Finding identity

`identity_key = sha256(repo | source | head-path | rule | normalized message | normalized anchor text)`; `dedup_hash = sha256(identity_key | occurrence index)`. No line numbers. Inserting code above a finding does not change it; editing the flagged line does; whitespace changes do not; renames keep identity through a rename map. Known limits: renaming an identifier on the flagged line looks like fixed + new; identical repeated lines are told apart only by occurrence order. ([identity.py](../services/ai-review/analysis/identity.py), [test_identity.py](../services/ai-review/tests/test_identity.py))

## 17. Security model

Repository content is treated as hostile input. Controls and their tests are tabulated in [phase0-hardening-report.md](phase0-hardening-report.md) (which distinguishes executed proofs-of-concept from source inspection) and [architecture.md](architecture.md) (trust boundaries). Summary: no PR-supplied config executes; subprocesses get an allowlisted environment; paths are validated and passed after `--`; control files are never written; findings are secret-redacted; internal endpoints need a shared secret and fail closed; internal pages are 404 unless enabled and then Basic-auth-gated; production refuses to start without a durable store; FastAPI docs are off outside development/test. **It is not a sandbox** (no container, seccomp, or network isolation).

## 18. Reliability model

Events survive failures (reclaimed from stored payloads); jobs survive restarts (a row, a lease, bounded attempts); stale runs are superseded deterministically; incomplete analysis is `partial`, never `completed`; pagination cannot silently truncate. Remaining reliability gaps are listed in §29.

## 19. Current frontend

`apps/web` is deliberately thin: the webhook receiver; `/api/status` (reports only `ok`/`unreachable`); `/` (status page; copy corrected in Phase 0 to say there is no AI reviewer); `/setup` (post-install page; copy corrected to say comments are not posted yet); `/internal/installations` (debug table, 404 unless `INTERNAL_PAGES_ENABLED=true`, then HTTP Basic auth via [middleware.ts](../apps/web/middleware.ts)). No dashboard exists. Next.js build verified locally, and the middleware behavior was checked against a real `next start`.

## 20. Current backend

`services/ai-review/app/`: settings with fail-closed production validation ([config.py](../services/ai-review/app/config.py)), internal-secret auth, event handlers, delivery ingest/sweeper ([ingest.py](../services/ai-review/app/ingest.py)), store abstraction with in-memory and Supabase implementations ([store.py](../services/ai-review/app/store.py)), the worker ([worker.py](../services/ai-review/app/worker.py)), and the job runner ([review_runner.py](../services/ai-review/app/review_runner.py)). The `analysis/` package can also run standalone: `python -m analysis.run <repo> <files>` (not differential).

## 21. Database architecture

Migrations `0001`–`0004` in [supabase/migrations/](../supabase/migrations/). They parse with `sqlglot` (dialect `postgres`) but have **not been executed** against Postgres.

| Table | Purpose |
|---|---|
| `installations`, `repositories` | GitHub App installs and their repositories (`is_active`) |
| `pull_requests` | PR rows with `head_sha`, `base_sha`, `github_updated_at` (stale-event guard) |
| `review_runs` | the durable job: SHAs, `attempts`, lease/not-before `available_at`, `analysis_meta`, `error_code`, status |
| `webhook_deliveries` | delivery state machine with stored payload |
| `findings` | normalized findings + `identity_key`, `change_status`, `moved`, `in_diff`, `base_start_line` |

No row-level-security policies are defined in the migrations; the backend uses the service-role key server-side only. The `vector` extension is enabled but no table uses it.

## 22. Current API routes

| Route | Where | Auth | Purpose |
|---|---|---|---|
| `POST /api/github/webhook` | web | GitHub HMAC | public webhook receiver |
| `GET /api/status` | web | none | liveness (`ok`/`unreachable` only) |
| `GET /`, `GET /setup` | web | none | informational pages |
| `GET /internal/installations` (page) | web | Basic auth, off by default | debug view |
| `GET /health` | backend | none | liveness; reveals no configuration |
| `POST /internal/webhook/pull-request` | backend | internal secret | event ingest (all three event types) |
| `GET /internal/review-runs/{id}` | backend | internal secret | job status + `analysis_meta` |
| `POST /internal/review-runs/{id}/retry` | backend | internal secret | manual retry of a `failed` run only |
| `GET /internal/installations` | backend | internal secret | data for the debug page |

## 23. Testing strategy

Real tools where feasible (ESLint and Semgrep actually run), mocks only for the outside world: GitHub is a `respx` fake ([fake_github.py](../services/ai-review/tests/fake_github.py)); the database is the in-memory store. Key suites: security proofs-of-concept ([test_security_poc.py](../services/ai-review/tests/test_security_poc.py)), state machines, snapshot fetcher, differential, identity, worker, production hardening, scope guards ([test_scope_guards.py](../services/ai-review/tests/test_scope_guards.py): no AI SDK, no GitHub write calls, no unrelated products), and a **local, mocked** end-to-end test ([test_e2e_local_mocked.py](../services/ai-review/tests/test_e2e_local_mocked.py)).

## 24. Current test results (last full run, Phase 0)

| Check | Result |
|---|---|
| Backend `python -m pytest` | 388 passed, 1 skipped (POSIX-only proof-of-concept), 0 failed |
| Web `npm run test` | 38 passed |
| `ruff check .`, `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| Migrations | parse with `sqlglot`; **not executed** |
| Real GitHub / Supabase / Render / Vercel / production end-to-end | **not verified** |

## 25. What is actually implemented

See the status table below. In one line: Phase 0's hardened static-analysis pipeline, durable events/jobs, differential classification, and finding identity — verified locally.

## 26. What is partially implemented

- **Persistence:** full contract implemented for two stores; only the in-memory one has been exercised.
- **CI:** workflow exists; it has not run on this repository state, so the Ubuntu-only proof-of-concept has never executed.
- **Findings for evaluation:** stored with identity and change status, but no consumer/aggregation exists.
- **GitHub App:** auth code and webhook plumbing exist; no App is registered.

## 27. What is not implemented

AI/LLM review of any kind; posting comments or reviews to GitHub; approve/merge (deliberately never); an evaluation harness, datasets, ground-truth tooling, metrics, and reports; a dashboard; RAG; multi-agent review; multiple LLM providers; a Vercel-side webhook inbox; containerized/network-isolated analysis; billing; multi-language analysis beyond JavaScript/TypeScript.

## 28. Known limitations

- Semgrep runs **six hand-written rules**, not Semgrep's registry coverage; results must never be labeled "Semgrep's accuracy" ([semgrep-rules/README.md](../services/ai-review/analysis/semgrep-rules/README.md)).
- ESLint runs its baseline (`eslint:recommended` + `@typescript-eslint/recommended`); parse errors appear as `eslint-fatal-error` findings.
- Secret redaction is pattern-based.
- One worker thread handles one PR at a time.
- More than 200 analyzable changed files fails the run (`too_many_files`) rather than being partially reviewed.
- Free-tier cold-start, CPU, and memory behavior is unmeasured.
- The repository's own ESLint config is deliberately ignored (a Phase 3 feature removed for security).

## 29. Known architectural gaps

1. **No Vercel-side webhook inbox.** Durability starts when the event reaches the backend. If Render is asleep or down, `apps/web` returns 502 and the event is stored nowhere Codentry controls; GitHub does not retry automatically; recovery is a manual "Redeliver".
2. **Not a sandbox.** Scrubbed env + resource flags + process-tree kill, but no container/seccomp/network namespace.
3. **`SupabaseReviewStore` and migration `0004` unexercised** against live Postgres; `finalize` is four PostgREST calls, not one transaction.
4. **No real end-to-end run** on any real service.
5. **Basic auth** for the internal debug page is adequate for a team view only.

## 30. Current deployment status

**Nothing is deployed.** No GitHub App, Supabase project, Render service, or Vercel project exists. [first-deployment-runbook.md](first-deployment-runbook.md) is the ordered procedure; it is USER ACTION REQUIRED. With `ENVIRONMENT=production`, the backend refuses to start without Supabase credentials and the internal secret.

## 31. Current research/evaluation readiness

Foundation ready for an **offline** harness that calls `analysis/` on pinned snapshots (Phase 0 report, section J). **Not** ready to use the deployed pipeline's data as evidence, and no measurement has been made. Nothing in this repository is a result. Prerequisites still missing: case format, ground-truth sources, matching/metrics code, statistical reporting, reproducible run records — see [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md).

## 32. Glossary

| Term | Meaning here |
|---|---|
| Arm | One review signal in an experiment (A = static analysis; B = AI only; C = static + AI; D = second model — not planned) |
| Base / head / merge base | The PR's target commit / the PR's newest commit / their common ancestor (used for "before") |
| Differential analysis | Analyzing both sides and reporting only what changed |
| Finding | One normalized tool result: source, rule, severity, file, lines, description |
| Identity key | Content-anchored identity of a finding, independent of line number |
| Lease / fencing token | Time-limited ownership of a job / an attempt counter that stops a stale worker from writing |
| Ground truth | Independent evidence of what is truly defective (tests, seeded mutants, verified historical bugs, human labels) |
| Mutation-seeded defect | A defect deliberately injected by a small code transformation |
| SAST | Static application security testing |
| Superseded | A run whose head commit is no longer the PR's current head |
| Trusted config | Analysis configuration from Codentry's baseline (+ sanitized base-commit overlay), never from the PR |

---

## Status table

| Area | Status | Evidence | Notes |
|---|---|---|---|
| Webhook receiver (HMAC, allowlist, rate limit, honest 502) | IMPLEMENTED, VERIFIED LOCALLY | [webhook.test.ts](../apps/web/tests/webhook.test.ts), [github-webhook.test.ts](../apps/web/tests/github-webhook.test.ts) | Never received a real GitHub delivery. NOT VERIFIED IN PRODUCTION. |
| Durable delivery state machine + sweeper | IMPLEMENTED, VERIFIED LOCALLY | [test_store_state_machines.py](../services/ai-review/tests/test_store_state_machines.py), [test_webhook_endpoint.py](../services/ai-review/tests/test_webhook_endpoint.py) | In-memory store only. |
| Durable job queue (lease, fencing, backoff, supersede) | IMPLEMENTED, VERIFIED LOCALLY | [test_store_state_machines.py](../services/ai-review/tests/test_store_state_machines.py), [test_worker.py](../services/ai-review/tests/test_worker.py) | Supabase implementation unexercised. NOT VERIFIED IN PRODUCTION. |
| `SupabaseReviewStore` | PARTIALLY IMPLEMENTED | [store.py](../services/ai-review/app/store.py) | Implemented to the same contract; never run against Postgres. |
| Migrations 0001–0004 | PARTIALLY IMPLEMENTED | [supabase/migrations/](../supabase/migrations/) | Parse with sqlglot; not executed. |
| Pinned, paginated GitHub snapshot | IMPLEMENTED, VERIFIED LOCALLY | [test_analysis_changed_files.py](../services/ai-review/tests/test_analysis_changed_files.py) | Mocked HTTP only; not real GitHub. |
| Trusted-config policy (no PR config) | IMPLEMENTED, VERIFIED LOCALLY | [test_security_poc.py](../services/ai-review/tests/test_security_poc.py), [test_trusted_config.py](../services/ai-review/tests/test_trusted_config.py) | Executed proofs-of-concept on Windows; Ubuntu-only PoC not yet run. |
| Subprocess isolation (env scrub, argv/path hardening) | IMPLEMENTED, VERIFIED LOCALLY | [test_subprocess_env.py](../services/ai-review/tests/test_subprocess_env.py), [test_security_poc.py](../services/ai-review/tests/test_security_poc.py) | NOT a sandbox. |
| ESLint analysis (baseline config) | IMPLEMENTED, VERIFIED LOCALLY | [test_analysis_eslint_runner.py](../services/ai-review/tests/test_analysis_eslint_runner.py) | JS/TS only. |
| Semgrep analysis (6 own rules) | IMPLEMENTED, VERIFIED LOCALLY | [test_semgrep_ruleset.py](../services/ai-review/tests/test_semgrep_ruleset.py) | Small ruleset; see limitations. |
| Differential classification | IMPLEMENTED, VERIFIED LOCALLY | [test_differential.py](../services/ai-review/tests/test_differential.py), [test_review_runner.py](../services/ai-review/tests/test_review_runner.py) | No real-PR validation. |
| Content-anchored finding identity | IMPLEMENTED, VERIFIED LOCALLY | [test_identity.py](../services/ai-review/tests/test_identity.py) | Stability across real refactors unmeasured. |
| Secret redaction | IMPLEMENTED, VERIFIED LOCALLY | [test_redact.py](../services/ai-review/tests/test_redact.py) | Pattern-based; will miss bespoke formats. |
| Production fail-closed config | IMPLEMENTED, VERIFIED LOCALLY | [test_production_hardening.py](../services/ai-review/tests/test_production_hardening.py) | |
| Internal page gate (Basic auth, default 404) | IMPLEMENTED, VERIFIED LOCALLY | [internal-access.test.ts](../apps/web/tests/internal-access.test.ts) + manual `next start` check | |
| Local mocked end-to-end | IMPLEMENTED, VERIFIED LOCALLY | [test_e2e_local_mocked.py](../services/ai-review/tests/test_e2e_local_mocked.py) | Mocked GitHub + in-memory store; real ESLint/Semgrep. **Not production verification.** |
| Real GitHub / Supabase / Render / Vercel end-to-end | NOT IMPLEMENTED (never run) — NOT VERIFIED IN PRODUCTION | [first-deployment-runbook.md](first-deployment-runbook.md) | USER ACTION REQUIRED. |
| Vercel-side webhook inbox | NOT IMPLEMENTED | [architecture.md](architecture.md) gap #1 | |
| Container/network sandbox for analysis | NOT IMPLEMENTED | [architecture.md](architecture.md) gap #2 | |
| AI / LLM review (any provider) | NOT IMPLEMENTED | [test_scope_guards.py](../services/ai-review/tests/test_scope_guards.py) enforces absence | Planned only after an evaluation harness exists. |
| Posting comments / reviews to GitHub | NOT IMPLEMENTED | same test | Approve/merge deliberately never. |
| Evaluation harness, datasets, metrics | NOT IMPLEMENTED (PLANNED) | [evaluation/README.md](../evaluation/README.md), [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md) | Documentation only today. |
| Dashboard, billing, RAG, multi-agent, second LLM | NOT IMPLEMENTED | — | Explicitly out of scope for now. |
| GitHub Actions CI | PARTIALLY IMPLEMENTED | [ci.yml](../.github/workflows/ci.yml) | Workflow exists; has not run on this state. |
