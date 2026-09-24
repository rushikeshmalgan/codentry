# Codentry — What Changed From the Original Plan

**As of:** 24 September 2026. **Purpose:** explain how the project moved from the original concept to today's repository and research direction, so nobody has to reconstruct it from chat history.

**What "original plan" means here (no invention):** the original plan is what is written in `docs/Codentry_PRD.docx` (the PRD), the original `README.md` at git `HEAD` (`docs/backup/README.md.pre-docs-update-2026-09-24` is the current working copy before this task; `git show HEAD:README.md` is the committed original), and the *original* literature survey (`docs/backup/Codentry_Literature_Survey.original-2026-08-26.pdf`, generated 2026-08-26). Commits: `67d9600` first commit → `835d2de` Phase 1 foundation → `62283f0` README → `559bf37` Phase 2 GitHub integration → `d34744f` Phase 3 static analysis. **Phase 0 is not committed** (working tree only).

Related: [PROJECT_STATUS.md](PROJECT_STATUS.md) · [phase0-hardening-report.md](phase0-hardening-report.md) · [research-design.md](research-design.md) · [literature-survey-change-log-2026-09-24.md](literature-survey-change-log-2026-09-24.md)

---

## A. Original concept

From the PRD:

- "An AI-powered GitHub App that automatically reviews pull requests, combining deterministic static analysis (ESLint, Semgrep) with AI-driven judgment (Claude)", installed on a repository with no separate app to open.
- Audience: 4–5-person college project teams without a senior reviewer.
- **MVP definition:** every PR receives ESLint + Semgrep + Claude review, posted as real PR comments, with security mitigations NFR-3 to NFR-5.
- Free-tier hosting (Vercel, Render, Supabase) as a load-bearing constraint (NFR-1).
- Success metrics: precision/recall per source (never blended), a static-only baseline comparison, false-positive rate, adoption.
- Deferred: RAG, an evaluation harness ("Phase 6" in the original survey; "Phase 3" in the PRD's future-scope list), multi-agent review, dashboard polish, monetization.
- Novelty claim (original survey §9): a combination of a clean static/AI split with independent evaluation, free-tier deployability, PR-native interaction, and precision-first RAG — stated there as narrow.

## B. Phase 0 discoveries

Phase 0 was an audit of the code built in Phases 1–3 followed by hardening. It found (details and evidence labels in [phase0-hardening-report.md](phase0-hardening-report.md)):

- A PR's own `.eslintrc.js` / JSON `parser` / `extends` **executed on our server** (executed proof-of-concept).
- Every server secret was visible to the analysis subprocesses.
- A file named `--x.js` was parsed as a command-line option and its findings vanished; a drive-absolute path made `materialize()` write outside its workspace.
- A PR could hide its own findings (`.eslintignore`, `eslint-disable`, `// nosemgrep`) or switch rules off with its own config.
- Webhook events were recorded *before* processing, so a failure plus a retry made the event look like a duplicate and it was lost.
- Reviews were in-process background tasks: lost on restart, could stay `running` forever.
- GitHub state was not pinned to a commit and file listing silently stopped at 100 files.
- Whole-file analysis blamed pull requests for pre-existing findings; finding identity changed whenever line numbers shifted.
- Production could silently fall back to volatile memory; an internal page had no access control; public pages echoed backend errors.
- The original literature survey's reference list contained wrong author names for most entries (found in *this* task; see the survey change log).

## C. Current architecture

See [PROJECT_STATUS.md §7](PROJECT_STATUS.md) and [architecture.md](architecture.md). In short: webhook → durable delivery → durable job → pinned GitHub snapshot → base and head analysis with trusted configuration → differential classification → fenced finalize. No AI, no comment posting.

## D. Current research direction

"Evidence-first reviewer plus evaluation": the contribution is measuring accuracy, overlap, and noise of review signals on defensible ground truth, with AI as one optional later signal. See [research-design.md](research-design.md) and [literature-survey-updated-2026-09-24.pdf](literature-survey-updated-2026-09-24.pdf).

## E. Deferred features

AI/LLM reviewer (any provider); posting PR comments; the evaluation harness itself (planned, not built); authorship-stratified evaluation; a Vercel-side webhook inbox; container/network sandbox; dashboard; billing.

## F. Removed features

| Removed | Why |
|---|---|
| Honoring a repository's own ESLint config (a Phase 3 feature) | It was a code-execution primitive and let a PR disable its own review. |
| Warn-and-continue in-memory fallback in production | It silently lost every event and job on restart. |
| FastAPI `/docs` and `/openapi.json` outside development/test | They enumerated internal routes. |
| Line-number-based `dedup_hash` | Changed under unrelated edits; replaced by identity v2. |
| The Phase 3 three-rule Semgrep file `baseline.yml` | Replaced by `production.yml` (six rules); the SQL rule matched any string concatenation. |
| `environment` in `/health` output | Needless configuration disclosure. |

## G. New features and constraints (all from Phase 0)

Trusted-config policy; scrubbed subprocess environment; path/argv/control-file hardening; resource ceilings; secret redaction; durable delivery state machine + sweeper; durable job queue with leases and a single polling worker; pinned/paginated snapshot with completeness checks; differential classification; identity v2; `partial` and `superseded` run statuses; manual retry endpoint; production fail-closed startup; internal-page gate; `analysis_meta` reproducibility metadata; scope-guard tests; migration `0004`.

## H. Reasons for important changes

The unifying reason: a review tool whose output will be *measured* must first be trustworthy against hostile input, must not lose events, must analyze exactly the commits it claims to, and must count only what a change introduced. Otherwise any precision/recall number is uninterpretable.

---

## Change table

| Original Plan | Current Plan | Change Type | Reason | Impact |
|---|---|---|---|---|
| Generic "AI-powered code reviewer" (PRD §1) | Evidence-first PR analysis with differential static analysis and an *optional* AI signal | Reframing | An AI reviewer cannot be validated by itself; the contribution is measurement (see [research-design.md](research-design.md)) | Product copy, README callout, setup page, survey framing all changed |
| Honor the PR's own ESLint config (Phase 3 design) | Trusted baseline + sanitized **base-commit** overlay; PR config never trusted | Security fix / feature removed | Executed proof-of-concept: PR config executes code and can disable its own review | Repos lose custom rules unless committed to the base branch as sanitized JSON |
| Review as an inline FastAPI background task | Durable `review_runs` row + single polling worker with leases | Architecture | Tasks were lost on restart and could hang in `running` | Webhook returns after enqueue; job is a row; bounded attempts |
| GitHub state read "as it is now" | Pinned head SHA, merge base, and base SHA; head re-verified before/after | Correctness | Force-pushes and races produced reviews of the wrong code | New `superseded` status; explicit `head_moved` handling |
| Files list = first page (100), truncation logged only | Link-paginated, count-checked, >200 analyzable files fails the run | Correctness | A partial review must never look complete | `too_many_files` failure instead of a silent prefix |
| Whole-head-file findings | Differential: new / existing (moved?) / fixed vs. merge base | Core new capability | Blame only what the PR introduced; makes "false positives per PR" meaningful | Base analysis doubles tool runs; findings carry `change_status` |
| Line-number finding identity | Content-anchored identity v2 (+ occurrence index) | Correctness | Line drift changed identity | `dedup_hash` redefined; schema additions |
| One-tool failure = `completed` (Phase 3) | `partial` with recorded reasons | Honesty | Hid data loss | Consumers must treat `partial` as incomplete |
| Record delivery id before processing | Claim → process → mark `succeeded` last; payload stored; sweeper | Reliability | Failures + retries were swallowed as duplicates | Redelivery of failed events now reprocesses |
| In-memory fallback everywhere | Only in development/test; production refuses to start | Fail-closed | Volatile state looked healthy | Deploy needs Supabase configured first |
| Internal debug page reachable by URL | 404 unless enabled, then Basic auth | Security | Exposed installation/repository names | New `INTERNAL_PAGES_*` env vars |
| Public pages echoed backend errors; `/health` showed environment | Generic `ok`/`unreachable`; no config in `/health` | Security | Information disclosure | Detail moved to server logs |
| Static output feeds Claude (PRD FR-3) | AI removed from scope until an evaluation harness exists | Deferred | Cannot claim AI value without measurement; prompt-injection surface | PRD MVP definition is **no longer the near-term target** |
| PR comments as the deliverable (PRD FR-6, MVP) | Findings stored only; comments planned later | Deferred | Evaluation and correctness first; write access unused | GitHub App still requests PR write permission for the future |
| "AI catches bugs" | Measurable comparison of independent signals (arms A/B/C) | Research design | Coverage, precision, noise, overlap must be measured | New metrics and ground-truth requirements |
| RAG / pgvector (survey Theme A; "Phase 4") | Demoted; not a committed requirement | Deferred / demoted | Literature evidence is mixed and partly unverified (survey change log) | `vector` extension enabled but unused |
| Multi-agent review (survey Theme C; PRD future scope) | Out of scope | Deferred | Complexity, cost, and attack surface; independence measurement is what matters | Survey keeps it as related work only |
| Multiple LLM providers | Deferred; arm D (second model) explicitly not now | Deferred | Scope | — |
| Original survey's "unique combination" claim (Table 1: "YES (unique)") | "Limited evidence in the selected corpus"; no uniqueness claim | Claim weakened | The corpus was team-selected; not a systematic search | Positioning in FYP report must use careful wording |
| Original survey's reference list | Verified against arXiv; author names corrected; text errors corrected | Correction | 27 of 30 first-author names did not match arXiv | Survey change log lists each correction |
| Evaluation harness as "Phase 6", after AI and RAG | Evaluation moved to the center; harness precedes any AI | Reordering | Ground truth and metrics are the contribution | [8_DAY_IMPLEMENTATION_PLAN.md](8_DAY_IMPLEMENTATION_PLAN.md) puts the harness first |
| CodeArena / coding-assessment / judge / trainer ideas | Explicitly unrelated; not in the repository | Scope boundary | Different product | `test_scope_guards.py` checks the repository |

## Changes found in the repository that were not in the list above

1. **Migration `0004`** adds columns to four tables and two indexes; it has never run against Postgres.
2. **`review_runs` uniqueness** on `(pull_request_id, head_sha)` makes re-review of the same commit impossible without a manual retry.
3. **The CLI (`python -m analysis.run`) is not differential**; its findings have `change_status = null`.
4. **`GitHubAuthError` now carries `status_code`** so auth failures can be classed retryable vs permanent.
5. **`requirements-dev.txt` gained PyYAML** (already installed transitively via Semgrep) for the ruleset tests.
6. **Stale statements still present** (found while writing this document, deliberately *not* edited beyond a pointer): the root `package.json` description and most of the README body still describe an "AI-powered" reviewer; the README now has a "Current state" callout that supersedes them. The PRD is unchanged and still describes the original MVP.
7. **`.kilo/`** — an ignored directory from another tool (contains a copy of the PRD and survey). Not part of the project; untouched.
8. **CI has not run** on the Phase 0 state, so the Ubuntu-only PoC and the CI workflow itself are unverified.
