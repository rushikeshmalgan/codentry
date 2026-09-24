# Codentry — Final Product Definition, Architecture & Pricing

**As of:** 24 September 2026. **Nothing described as "final" here exists yet unless it is marked IMPLEMENTED.** Current state: [PROJECT_STATUS.md](PROJECT_STATUS.md). Deployment alternatives: [NO_COST_ALTERNATIVES.md](NO_COST_ALTERNATIVES.md). Schedule: [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md).

## 0. How to read this document

Every capability is tagged with **one** layer:

| Tag | Meaning |
|---|---|
| **[A] Implemented** | exists in the repository today (Phase 0), verified locally only |
| **[B] MVP** | required for a minimum usable product (PRD-style: something a team can install and get value from) |
| **[C] Research/FYP** | required to answer the research question and defend it at review |
| **[D] Future** | optional; not needed for B or C |

Future features are never described as existing.

## 1. Two layers, deliberately separate

```
PRODUCT LAYER                                       RESEARCH LAYER
GitHub PR → analysis → findings →                   controlled inputs (pinned cases)
  evidence → review output                              ↓
  (webhook, worker, GitHub snapshot,                independent analysis arms (A, B, C)
   ESLint/Semgrep, differential,                        ↓
   [B] comments)                                    common evaluator (same matching rules)
                                                        ↓
                                                    ground truth (tests · mutants · verified bugs · human labels)
                                                        ↓
                                                    metrics (precision, recall, FP/PR, localization, duplicates, cost, latency + intervals)
                                                        ↓
                                                    empirical comparison (report with limitations)
```

The research harness must be runnable **without** the web app, GitHub, or a database: it consumes pinned cases and calls `analysis/` directly. The production UI must never be a dependency of an experiment, and production code must never import the harness (enforced by `tests/test_scope_guards.py`).

## 2. Target users and teams

| Group | Role | Layer |
|---|---|---|
| Small student/project teams (4–5 members, no senior reviewer) | Primary product user, per the PRD | [B] |
| The Codentry team and reviewers | Consumers of experiment reports | [C] |
| Small commercial teams (≈10–50 developers) | Possible later users | [D] |
| Enterprises (self-hosting, custom rules, audit) | Possible much later | [D] |

## 3. Primary workflow and user journey

1. A team installs the GitHub App on a repository (needs the App registered first — USER ACTION REQUIRED). **[B]**
2. A developer opens or updates a pull request.
3. Codentry analyzes exactly that head against its merge base and records what the PR introduced. **[A]**
4. **[B]** Codentry posts a small number of *new* findings, each with tool, rule, location, and evidence, as PR comments — never approving, requesting changes, or merging.
5. **[D]** The developer can mark a finding useful/not useful; the team can see history.
6. **[C]** Independently of the product, the same analysis code runs over a fixed set of cases and the results are compared to ground truth.

## 4. Capability definitions

### GitHub integration
- **[A]** Webhook receive/verify/forward; App JWT + installation token; pinned, paginated file/content fetch; installation/repository/PR bookkeeping.
- **[B]** App registered and installed; posting review comments through the Pull Requests API; comment de-duplication using finding identity across pushes; never `APPROVE`/`MERGE` (structural: no such call exists, enforced by a test).
- **[D]** Check runs/annotations, GitHub Marketplace listing, GitHub Enterprise Server.

### PR analysis, static analysis, differential analysis
- **[A]** ESLint (baseline + sanitized base-commit overlay) and Semgrep (six hand-written rules); base and head analysis; `new`/`existing`/`fixed`/`moved`; identity independent of line numbers.
- **[B]** Report only `new` findings that are `in_diff`; cap comments per PR; a documented rule policy.
- **[D]** More languages, a larger pinned ruleset (must be pinned reproducibly; registry packs fetch rules over the network), taint analysis, container/network sandbox.

### AI review
- **[A]** Nothing. There is no AI code, SDK, prompt, or AI finding in the repository, and a test fails if one appears.
- **[C]** A *minimal* AI arm inside the evaluation harness only, gated on the harness and ground truth existing: pinned model ID and parameters, structured output validated against a schema, every finding's quoted evidence checked against the real lines, several repeated runs per case (LLM output is non-deterministic), token/latency/cost recorded. No RAG, no second provider, no multi-agent.
- **[B]** Only if the research shows value: the same arm behind a feature flag with prompt isolation (untrusted code separated from instructions) and output validation before anything is posted.
- **[D]** RAG, a second model, multi-agent review, fine-tuning.

### Evidence model
Every finding carries *what produced it* (`source`, rule id), *where* (file, lines), *what code* (an anchor used for identity), and *relative to what* (`change_status`, merge-base SHA), plus run-level reproducibility metadata (`analysis_meta`: tool versions, ruleset SHA-256, baseline-config SHA-256, config source, skip reasons). **[A]** An AI finding, when it exists, must additionally quote the exact code it refers to and be discarded if the quote does not match the file. **[C]**

### Finding model
**[A]** [packages/schemas/review.schema.json](../packages/schemas/review.schema.json) and `analysis/finding.py`: source, category, severity, title, description, file/lines, `identity_key`, `dedup_hash`, `change_status`, `moved`, `in_diff`, `base_start_line`. Confidence is `null` for static findings by design; AI confidence is **not** to be shown to users as a raw decimal (research-design rule).

### Evaluation model
**[C]** Arms: A (static, implemented), B (AI only), C (static + AI); D (second model) is explicitly not planned. Ground truth in order of preference: executable tests; mutation-seeded defects; verified real defects; independent human labels (≥2 labelers, agreement reported). **Never** an AI judging an AI. Metrics reported per arm, never blended into one score: precision, recall, false positives **per PR**, findings per changed line, location accuracy, duplicate rate, overlap between arms, latency, cost — each with an interval (small samples give wide intervals; the Wilson interval is the default for proportions). Same-model bias, non-determinism, contamination, and mutant realism are recorded as threats to validity. Details: [research-design.md](research-design.md).

### Reporting and review feedback
- **[C]** Reproducible run records (inputs, tool/model versions, prompt hash, seeds) and generated reports with intervals and limitations; one command re-runs Arm A and checks the report hash.
- **[B]** PR comments as above. **[D]** Optional dashboard (PRD FR-8 calls it secondary), useful/not-useful feedback loop.

### Deployment model
- **[A]** Blueprint/env documentation ([render.yaml](../render.yaml), [deployment.md](deployment.md), [first-deployment-runbook.md](first-deployment-runbook.md)); production fails closed without a durable store.
- **[B]** One real end-to-end run on real GitHub/Supabase/Render/Vercel, recorded honestly; backend kept warm or on an always-on plan (a webhook must be answered within 10 seconds).
- **[D]** Container image with a non-root user and no network for the analysis step; multi-region; self-hosting.

### Security model
- **[A]** Trust boundaries in [architecture.md](architecture.md): no PR-controlled config, scrubbed subprocess env, path/argv hardening, secret redaction, internal-secret auth, gated internal pages, fail-closed production.
- **[B]** Before any comment posting: rate/volume caps, escaping of any repository-derived text placed in a comment, and (if AI is enabled) structural prompt separation and output anomaly checks. The literature reports that AI review agents on GitHub can be hijacked through PR text and can exfiltrate secrets when they hold credentials ([literature survey](literature-survey-updated-2026-09-24.pdf), refs [56], [57]); the AI arm must therefore run **without repository credentials**.
- **[D]** Real sandbox (container + seccomp + no network), audit log, SSO.

### Scalability considerations
The design supports multiple workers (compare-and-swap claim, fencing token) but a **single worker thread** is what runs today; one PR is processed at a time; GitHub REST limits for installation tokens are 5,000 requests/hour (scaling with repositories/users up to 12,500; 15,000 on Enterprise Cloud) per [GitHub Docs](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) (checked 2026-09-24). A review costs roughly one request per changed analyzable file per side plus about 6 fixed calls (pull, compare, file-list pages, config), so a 20-file PR is on the order of 50 requests — an estimate from the code, not a measurement. **[A]/[D]**

### Observability
**[A]** Structured JSON logs; per-run `status`, `error_code`, `latency_ms`, `attempts`, `analysis_meta`. **[B]** Basic run-failure alerting and a "stuck job" query. **[D]** Metrics/tracing dashboards.

### Future enterprise capabilities
**[D]** Self-hosted deployment, custom/private rule packs, SSO/RBAC, audit logs, data-residency options, retention policies, support. None exist; none are needed for B or C.

## 5. Capability matrix

| Capability | [A] now | [B] MVP | [C] Research/FYP | [D] Future |
|---|---|---|---|---|
| Webhook + durable jobs + pinned snapshot | ✔ (local) | real deployment | — | scale-out |
| ESLint + 6-rule Semgrep, differential | ✔ (local) | rule policy | as Arm A | larger pinned rulesets |
| Finding identity + change status | ✔ (local) | comment de-dup | duplicate-rate metric | feedback loop |
| Post PR comments | ✘ | ✔ | not required | check runs |
| AI review | ✘ | conditional on results | minimal arm (gated) | RAG / 2nd model / multi-agent |
| Evaluation harness, datasets, ground truth, metrics | ✘ | — | **✔ required** | public benchmark release |
| Dashboard | ✘ | — | — | ✔ |
| Sandboxed analysis | ✘ | recommended | — | ✔ |

---

## 6. Pricing research (checked 24 September 2026)

**Method.** Official pages were fetched on 2026-09-24 through a summarizing web-fetch tool; figures are quoted from what it returned. Where a page could not be retrieved (HTTP 403, login redirect, or navigation-only content), the row says so and nothing is invented. Prices are USD, exclude taxes, and change; re-check before committing money. Conversion to INR is deliberately not done here (it depends on the day's rate).

**Only services Codentry actually uses or could reasonably use are listed.**

| Provider | Product | Free tier | Paid tier | Important limits | Does Codentry need paid? | Source (checked 2026-09-24) |
|---|---|---|---|---|---|---|
| Vercel | Hosting for `apps/web` | Hobby $0: 1M edge requests, 100 GB transfer, 1M function invocations, 4 CPU-hrs; functions up to 300 s | Pro $20/mo + $20 per additional developer seat; usage-based overage | Hobby "restricts users to non-commercial, personal use only" (Vercel docs) | FYP demo: no. Any commercial use: Pro | [vercel.com/pricing](https://vercel.com/pricing), [docs/plans/hobby](https://vercel.com/docs/plans/hobby) |
| Render | Web service for `services/ai-review` | Free: 750 instance-hours/month; **spins down after 15 min without inbound traffic; ~1 minute to spin up**; no persistent disk; docs say "Do not use them for production applications" | Workspace: Hobby $0 / Pro $25 / Scale $499 per month. An always-on Starter web service plus a Basic-256mb Postgres on a Hobby workspace "typically ran about $13/month" (July 2026). Starter ≈ $7/mo (512 MB, 0.5 CPU) and Standard ≈ $25/mo (2 GB, 1 CPU) appear in third-party summaries only — **the official pricing page returned no figures; treat as unverified** | Free service loses local filesystem on spin-down; cold start collides with GitHub's 10 s webhook timeout | Yes for anything real (the worker must stay alive) | [render.com/docs/free](https://render.com/docs/free), [Render article, 2026-07-08](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses) |
| Supabase | Postgres (`supabase-py`) | Free: 500 MB database, 2 active projects, 5 GB egress, 1 GB storage; **projects paused after 1 week of inactivity** | Pro from $25/mo (8 GB disk, 250 GB egress, daily backups 7 days); Micro compute included, larger compute $15+/mo | Pausing breaks a demo left idle | Free is enough for FYP if kept active; Pro for anything real | [supabase.com/pricing](https://supabase.com/pricing) |
| GitHub | GitHub App, REST API, Actions | Installation-token limit 5,000 req/h (scales to 12,500; 15,000 Enterprise Cloud); Actions: 2,000 free minutes/month on private repos (Free plan), free standard runners on public repos | Actions overage $0.006/min (Linux 2-core) | Secondary limits: 100 concurrent requests, 900 points/min, 80 content-creating requests/min. **No fee for registering a GitHub App was found on the pages checked; treat as $0 but unverified.** | No | [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| Anthropic | Claude API (for the future AI arm) | No free API tier; "a small amount of free credits" for new users | Per million tokens (input / output): Haiku 4.5 $1 / $5; **Sonnet 5 $2 / $10** (introductory price made permanent; the $3/$15 increase "will not occur"); Opus 5.5 $4 / $20; Opus 5 $5 / $25; Fable 5.1 $10 / $50. Batch API −50%; cache reads 0.1× input | Claude 4.7-and-later tokenizers produce ≈30% more tokens for the same text; usage-tier rate limits | Only if the AI arm is built; cost is small at FYP scale (§7) | [platform.claude.com pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Google | Gemini API (alternative/second provider — arm D is not planned) | Free tier on several Flash/Flash-Lite models ("Free of charge"); **free-tier content is used to improve Google products** | e.g. Gemini 3.5 Flash-Lite $0.30 / $2.50 per M tokens; Gemini 3.8 Flash $0.75 / $3.75 (through 2026-12-31); batch −50%; price increases scheduled 2027-01-01 | Free-tier data-use clause is a problem for private code | Not needed; possible free evaluation on public/synthetic code only | [ai.google.dev pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| OpenAI | API (comparison only; not planned) | — | As returned by the tool: gpt-4.1-mini $0.40 / $1.60; gpt-5-nano $0.05 / $0.40; gpt-5.3-codex $1.75 / $14.00; batch −50%. **The model names were extracted by a summarizing tool from a page I could not otherwise inspect; low confidence.** | — | No | [developers.openai.com pricing](https://developers.openai.com/api/docs/pricing) |
| Semgrep | Open-source CLI (Community Edition) used locally | Engine LGPL-2.1; the pip-installed CLI has no per-seat fee | Semgrep AppSec Platform: free up to 10 contributors / 10 repos (with Pro Engine features); Teams from $30/contributor/month | Codentry runs its **own six rules** locally; it does not use the platform | No | [semgrep.dev/pricing](https://semgrep.dev/pricing), [github.com/semgrep/semgrep](https://github.com/semgrep/semgrep) |

(Neon, Cloudflare, Oracle Cloud Always Free, and local options are priced in [NO_COST_ALTERNATIVES.md](NO_COST_ALTERNATIVES.md).)

## 7. Cost model

### 7.1 AI cost per review — an **assumption**, not a measurement

No AI arm exists, so there is **no measured token usage**. For arithmetic only, assume one review = **8,000 input tokens** (diff, surrounding code, static findings, instructions) and **1,000 output tokens**. Real usage depends on PR size, context policy, and the tokenizer; measure it before budgeting.

| Model | Input $/M | Output $/M | Cost / review (8k in, 1k out) | With Batch API (−50%) |
|---|---|---|---|---|
| Claude Haiku 4.5 | 1 | 5 | $0.013 | $0.0065 |
| Claude Sonnet 5 | 2 | 10 | $0.026 | $0.013 |
| Claude Opus 5.5 | 4 | 20 | $0.052 | $0.026 |
| Gemini 3.5 Flash-Lite (paid) | 0.30 | 2.50 | $0.0049 | $0.0025 |

Formula: `cost = input_tokens × input_price / 1e6 + output_tokens × output_price / 1e6`. Batch pricing applies to non-real-time work such as evaluation runs, not to PR-time review.

### 7.2 Scenarios (all monthly, USD, assumptions stated)

Reviews per month = PRs × average pushes per PR. AI model assumed: Claude Sonnet 5 at $0.026/review (§7.1) unless noted. Infrastructure prices from §6 (Render Starter/Standard figures are the unverified ones).

**1. Student / FYP demo** — assumptions: one test repository, ≈50 real PR events for the demo, plus an evaluation campaign of 200 cases × 3 repeated runs = 600 model calls (repeats because output varies between runs).

| Item | Cost |
|---|---|
| Vercel Hobby | $0 (non-commercial academic demo; the team must decide whether that fits Vercel's terms) |
| Render Free | $0 — **cold start ≈ 1 min vs GitHub's 10 s timeout**: warm it before the demo or use Starter (≈$7, unverified) |
| Supabase Free | $0 — project pauses after 1 week idle; keep it active |
| GitHub | $0 |
| AI evaluation (600 × $0.026) | ≈ $15.6 (≈ $7.8 with Batch). $0 if the AI arm is skipped or a Gemini free tier is used on public code only |
| **Total** | **≈ $0–$16 one-off** (≈ $7 more if Render Starter is used for the demo month) |

**2. Small team** — assumptions: 5 developers, 3 repositories, 80 PRs/month × 2.5 pushes = **200 reviews/month**.

| Item | Cost |
|---|---|
| Vercel | $0 Hobby if non-commercial, else Pro $20 |
| Render Starter (always-on) | ≈ $7 (unverified) |
| Supabase | $0 (Free, must stay active) or $25 (Pro) |
| AI (200 × $0.026) | ≈ $5.2 |
| **Total** | **≈ $12 – $57 / month** |

**3. Small production deployment** — assumptions: 50 developers, 1,000 PRs/month × 2.5 = **2,500 reviews/month**, commercial use.

| Item | Cost |
|---|---|
| Vercel Pro | $20 |
| Render Standard (2 GB) | ≈ $25 (unverified) |
| Supabase Pro | $25 |
| AI (2,500 × $0.026) | ≈ $65 |
| GitHub API (≈ 2,500 × ~50 ≈ 125k requests/month ≈ 170/h average vs 5,000/h limit) | $0 |
| **Total** | **≈ $135 / month** — before monitoring, backups beyond defaults, and a sandbox, which are unsized |

**4. Larger team / future** — assumptions: 500 developers, 10,000 PRs/month × 2.5 = **25,000 reviews/month**.

| Item | Cost |
|---|---|
| AI (25,000 × $0.026) | ≈ $650 (lower with prompt caching, Haiku 4.5, or Batch for non-urgent work; higher with Opus) |
| Several always-on workers and a larger database | **unsized** — depends on measured CPU/memory per review, which has never been measured |
| A real sandbox tier, monitoring, support | **unsized** |
| Semgrep Teams (only if the team *chooses* the commercial platform; not required by Codentry) | 500 × $30 = $15,000 — listed to prevent surprise, not a recommendation |
| **Total** | **≈ $650 AI + unsized infrastructure**; no exact bill can be claimed |

### 7.3 What actually drives cost

1. Model choice and tokens per review (this dominates after ~500 reviews/month).
2. Whether the worker must stay always-on (Render Free cannot be always-on).
3. Labeling time for ground truth — a human cost, not a cloud cost, and the largest one for the research project.

### 7.4 Things this document does not know

Real token usage; real CPU/memory per review; Render's official instance prices; whether GitHub charges anything for the App itself; INR conversion; taxes; any negotiated or academic discounts (Anthropic's page says academic discounts "may be available" — not investigated).
