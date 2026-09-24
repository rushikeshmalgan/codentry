# Codentry — No-Cost and Near-Zero-Cost Deployment Alternatives

**As of:** 24 September 2026. **Goal:** show how Codentry can be built, demonstrated, and *evaluated* without a large budget — and where "free" stops being honest.

Prices and limits are from official pages fetched on 2026-09-24 (see the price sheet in [FINAL_PRODUCT_AND_PRICING.md §6](FINAL_PRODUCT_AND_PRICING.md)); anything not verified is labeled. **Free is not a reason to recommend something**; each option lists what it cannot do.

## 0. The most important point

The research contribution (the evaluation harness, [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md)) needs **no hosting at all**: it reads pinned cases from disk, calls the `analysis/` package, and writes JSON/Markdown reports. It runs on a laptop or a GitHub Actions runner. The hosted stack (Vercel + Render + Supabase + a GitHub App) is only needed for the *product demonstration* of real pull requests. Do not let hosting problems block the research.

## 1. Options by concern

### 1.1 Frontend / webhook edge (`apps/web`)

| Option | Can do | Cannot do / limits | FYP | Research eval | Production | Migration | Source |
|---|---|---|---|---|---|---|---|
| **Vercel Hobby** (current plan) | Next.js hosting; 1M edge requests, 100 GB transfer, 1M invocations, functions up to 300 s | "Non-commercial, personal use only"; runtime logs 1 hour; no log drains | Yes | Not needed | **No** (commercial) → Pro $20/mo | none (current) | [Vercel Hobby docs](https://vercel.com/docs/plans/hobby) |
| **Cloudflare Workers/Pages** | Global edge; Workers Free 100,000 requests/day; paid from $5/mo | Free plan: **10 ms CPU per invocation**. Running this Next.js app there needs an adapter — **not investigated**, so compatibility (Node `crypto` HMAC, `fetch` timeouts) is unknown | Possible but unverified | Not needed | Possible (paid) | Medium–high, unverified | [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) |
| **No web tier: GitHub Actions on `pull_request`** (an alternative *deployment mode*, not implemented) | Runs analysis inside GitHub's runner; no webhook server, no Vercel, no Render; free for public repos, 2,000 min/month on private (Free plan) | Different architecture from the GitHub App (no durable queue, no installation model); GitHub warns against `pull_request_target`/`workflow_run` with untrusted code and recommends treating untrusted input as data ([secure-use](https://docs.github.com/en/actions/reference/security/secure-use)); I did not verify what token/secret access fork-triggered runs get | Yes, for a demo on repositories we own | **Yes** — good for running the harness on a schedule | Different product | New code | [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |

### 1.2 Backend (`services/ai-review`)

| Option | Can do | Cannot do / limits | FYP | Research eval | Production | Migration | Source |
|---|---|---|---|---|---|---|---|
| **Render Free** | Runs the FastAPI service | 750 h/month; **spins down after 15 min idle, ~1 minute to spin up**; local filesystem lost on spin-down; no persistent disk; docs: "Do not use them for production applications" | Demo only, **warm it up first** — a 1-minute cold start exceeds GitHub's 10 s webhook timeout and Vercel's 4 s forward timeout | Not needed | **No** | none (current) | [Render free](https://render.com/docs/free) |
| **Render Starter/Standard** | Always-on worker thread | ≈ $7 / ≈ $25 per month — **per-instance figures unverified** (official page returned none); a Render article says Starter + Basic-256mb Postgres ≈ $13/month (July 2026) | Optional for the demo month | Not needed | Yes | none | [Render article](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses) |
| **Oracle Cloud Always Free VM** | Always-on Linux VM; per Oracle's docs: Ampere A1 = **1,500 OCPU-hours and 9,000 GB-hours/month (≙ 2 OCPU, 12 GB)**, or 2 AMD micro VMs (1 GB), 200 GB block storage, 10 TB/month egress | **Idle instances "may be reclaimed"** (7-day 95th-percentile CPU/network <20%); you operate the OS, TLS, restarts, updates; account/verification requirements **not checked**; I have not run Codentry on it | Possible, high effort | Possible | Risky (reclamation) | Medium: needs a process manager, reverse proxy, TLS | [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |
| **Your own machine + a tunnel** (self-hosted) | Real webhooks reach a laptop for a live demo | Only up while the machine is; tunnel product limits **not investigated** | Yes, if rehearsed | Yes | No | Low | not researched |
| **Cloudflare Workers** | — | The backend is a Python FastAPI service with a subprocess-based analysis step; that does not run inside a 10 ms-CPU Worker. | No | No | No | Rewrite | [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) |

### 1.3 Database

| Option | Can do | Cannot do / limits | FYP | Research eval | Production | Migration | Source |
|---|---|---|---|---|---|---|---|
| **Supabase Free** (current) | Postgres, 500 MB, 2 projects, 5 GB egress, 1 GB storage | **Paused after 1 week of inactivity**; no SLA implied | Yes, keep it active | Not needed | No (pause) → Pro $25/mo | none | [Supabase pricing](https://supabase.com/pricing) |
| **Neon Free** | Postgres, 0.5 GB/project, 100 CU-hours/project/month, 100 projects, 10 branches | **Autosuspend after 5 min, cannot be turned off** (cold connections); `supabase-py` targets PostgREST, so switching means replacing the store implementation | Possible | Not needed | Paid Launch: $0.106/CU-h + $0.35/GB-month | Medium (new `ReviewStore`) | [Neon pricing](https://neon.com/pricing) |
| **Render Postgres Free** | — | **Expires 30 days after creation**, 1 GB, no backups | **No** | No | No | — | [Render free](https://render.com/docs/free) |
| **Local PostgreSQL** | Free; full control | Single machine; not a hosted service | Yes (dev) | Yes | No | Low | not researched |
| **SQLite / JSON files** (for the *research harness only*) | Zero infrastructure, reproducible, diff-able in git | Not the production store | Yes | **Yes — recommended** | No | none | — |

### 1.4 GitHub integration and webhooks

| Option | Can do | Cannot do / limits | FYP | Research | Production | Notes |
|---|---|---|---|---|---|---|
| **GitHub App** (current design) | Installation tokens, per-repo install, webhooks | Must be registered by someone with GitHub admin (USER ACTION REQUIRED). No registration fee found on the pages checked (unverified). GitHub does **not** auto-redeliver failed deliveries and requires a 2XX within 10 s ([webhook docs](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries)); API limit 5,000 req/h per installation, scaling with size ([rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)) | Yes | Not required | Yes | Current path |
| **Polling the GitHub API** (no inbound endpoint) | Works behind a firewall; good for batch analysis of chosen PRs | Latency; consumes rate limit; no installation events | Possible | **Yes** for collecting cases | Poor | Not implemented |
| **Pre-recorded cases from public repositories** | Full control and reproducibility | Not "live" | Yes | **Yes** | — | The harness's default input |

### 1.5 Static analysis

| Option | Can do | Limits | Source |
|---|---|---|---|
| **ESLint** (pinned baseline, current) | JS/TS rules, TypeScript parser | Baseline rules only; config is ours, not the repository's | [package.json](../services/ai-review/analysis/eslint-baseline/package.json) |
| **Semgrep Community Edition** (current) | Engine is LGPL-2.1; runs offline with our own six rules | Registry packs fetch over the network and were deliberately not used; the pricing page's free tier concerns the *platform*, not this CLI; rule-set licensing for registry rules **not verified** | [Semgrep repo](https://github.com/semgrep/semgrep), [pricing](https://semgrep.dev/pricing) |
| **CodeQL** | Semantic/taint analysis (a literature comparison reports it beside Semgrep) | Not integrated; licensing/limits for private repositories **not investigated** | — |

A literature caution applies to the static arm: a Node.js study found the three best tools combined detected up to 57.6% of 957 known vulnerabilities at 0.11% precision [37], so a small ruleset should be expected to have low recall on real defects. That is a result to measure, not a problem to hide.

### 1.6 AI (only for the future AI arm)

| Option | Can do | Limits | FYP | Research eval | Production |
|---|---|---|---|---|---|
| **Claude API (paid)** | Structured outputs; pinned model IDs; Batch −50% | No free API tier ("a small amount of free credits"); ≈ $8–16 for a 200-case × 3-run campaign under §7.1's *assumed* token counts | **Yes** | **Yes** | Yes |
| **Gemini API free tier** | Several Flash models "free of charge" | **Free-tier content is used to improve Google products** → do not send private code; no data-use guarantee for our own repos | Public/synthetic code only | Public code only | No |
| **Open-source local model via Ollama** | Ollama is MIT-licensed and runs open models locally with a REST API | README gave **no hardware guidance**; code-review quality of local models is **unverified**; results are not comparable with a hosted model | Possible | **Useful as an open-model baseline** — the LLM-in-SE guidelines recommend including one [48] | No |
| **OpenAI API (paid)** | Comparison provider | Not planned; arm D is out of scope | — | — | — |

Never use a model to label the ground truth for that same model's output (research-design rule; supported by [43]–[45]).

### 1.7 Background workers

| Option | Notes |
|---|---|
| In-process worker thread (current) | Zero cost; dies when the host sleeps; one job at a time |
| Render background worker | Paid; unpriced here |
| GitHub Actions `schedule` / `workflow_dispatch` | Free minutes; good for harness runs; not a webhook-driven queue |
| Cloudflare Queues | Free plan 10,000 operations/day; requires the Workers stack — not applicable to the Python service |

### 1.8 Logging, monitoring, storage

| Need | Free option (verified) | Limit |
|---|---|---|
| Logs | Vercel Hobby runtime logs; Render/Supabase dashboards (retention **not verified**) | Hobby keeps 1 hour of runtime logs and has no log drains ([Vercel docs](https://vercel.com/docs/plans/hobby)) |
| Monitoring | Structured JSON logs exist; no monitoring product was evaluated | Add a "stuck job" SQL query and a health check ping |
| File storage | Supabase Storage 1 GB free; GitHub Actions artifacts 500 MB and 10 GB cache (Free plan) | Reports/datasets are better kept in git |

## 2. Recommended stacks

### 2.1 ₹0 demo stack

```
apps/web        → Vercel Hobby            (non-commercial demo; team confirms terms)
backend+worker  → Render Free             (warm before the demo; ~1 min cold start)
database        → Supabase Free           (keep active; pauses after 1 week idle)
GitHub          → GitHub App (free)       (must be registered — USER ACTION)
analysis        → ESLint + Semgrep CE     (local, offline)
AI              → none (or a tiny paid Claude budget)
evaluation      → laptop / GitHub Actions, JSON+Markdown reports in git
fallback        → the local mocked end-to-end test + recorded run, clearly labeled "mocked"
```
Honest limits: Render Free is documented as not for production; a webhook that arrives while it is asleep is lost until manually redelivered; Vercel Hobby is non-commercial only.

### 2.2 Low-cost research stack (≈ US$10–100 total, mostly optional)

```
harness         → local machine + GitHub Actions; SQLite/JSON; no server
cases           → pinned public repositories + mutation-seeded variants (license-checked)
AI arm (if built)→ Claude API, pinned model, 3 repeats per case; Batch API for non-urgent runs; ≈ $8–16 for 600 calls under §7.1's assumption
open baseline   → Ollama model (recommended by the LLM-in-SE guidelines [48]); hardware permitting
hosted stack    → Render Starter for one month (≈ $7, unverified) for the single real end-to-end run
```

### 2.3 Low-cost production stack (≈ US$70–140 / month, small team)

```
apps/web        → Vercel Pro ($20)
backend+worker  → Render Standard (≈ $25, unverified) — or a self-managed VM (e.g. Oracle Always Free with reclamation risk)
database        → Supabase Pro ($25) — or Neon Launch (usage-based)
AI              → Claude Sonnet 5 or Haiku 4.5 (≈ $0.013–$0.026/review under §7.1's assumption)
sandbox         → NOT covered by any price above; needs a container with no network for the analysis step
```

## 3. What is NOT suitable, and why

| Do not use | Reason |
|---|---|
| Render Free for anything users depend on | Documented "not for production"; spins down |
| Render Postgres Free | Expires after 30 days; no backups |
| Supabase Free for continuity | Pauses after a week idle |
| Vercel Hobby for commercial use | Terms restrict it to non-commercial personal use |
| Gemini free tier for private repositories | Content is used to improve products |
| Cloudflare Workers Free for the Python backend | 10 ms CPU limit; wrong runtime |
| Neon Free where a cold connection matters | Autosuspend after 5 min cannot be disabled |
| Oracle Always Free for an unattended service | Idle instances may be reclaimed; you operate it |
| GitHub Actions with `pull_request_target` on untrusted code | GitHub's own guidance warns against it |

## 4. Not investigated (say so rather than guess)

CodeQL licensing/limits; tunnel product limits; hardware requirements and code-review quality of local models; Render Starter/Standard official prices; Oracle account requirements; any student/academic programs of the providers; log retention on Render and Supabase.
