# Codentry

**Codentry — AI-Powered GitHub Code Review Assistant**

Codentry is an AI-powered GitHub App that automatically reviews Pull Requests and provides actionable code-review feedback directly inside GitHub.

The project combines **deterministic static analysis** with **AI-based semantic reasoning** to identify bugs, security issues, code-quality problems, and potential improvements while keeping the review process native to GitHub.

> **Current MVP focus:** JavaScript / TypeScript repositories.

---

## 🚀 Why Codentry?

Traditional static analysis tools are excellent at detecting deterministic issues, but they can struggle with problems that require understanding the intent and context of the code.

AI code reviewers can reason about these higher-level issues, but may produce false positives or overlook deterministic violations.

Codentry combines both approaches:

```text
                    GitHub Pull Request
                           │
                           ▼
                    GitHub Webhook
                           │
                           ▼
                    Codentry Backend
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       Static Analysis              AI Review
       ESLint / Semgrep             Claude API
              │                         │
              └────────────┬────────────┘
                           ▼
                    Finding Normalization
                           │
                           ▼
                  GitHub PR Comments
```

This allows Codentry to study the effectiveness of:

* Static analysis alone
* AI review alone
* Combined static + AI review

---

## ✨ Key Features

### GitHub-Native Reviews

Codentry works as a GitHub App and reacts to Pull Request events.

Developers receive review feedback directly in the PR instead of having to switch to another dashboard.

### Deterministic Static Analysis

The MVP uses:

* **ESLint** for JavaScript/TypeScript code-quality and correctness rules
* **Semgrep** for security and pattern-based analysis

These tools provide reproducible findings that can be independently evaluated.

### AI-Powered Reasoning

The AI layer uses **Claude API** to analyze issues that may require:

* Semantic understanding
* Code context
* Correctness reasoning
* Security reasoning
* Understanding developer intent
* Repository conventions

The AI layer is designed to complement static analysis rather than simply repeat it.

### Repository Context

A later phase introduces repository-level context using retrieval and **pgvector**.

Rather than sending an entire repository to the model, Codentry can retrieve relevant files and code based on the Pull Request.

### Security-Aware AI Review

Repository code, comments, commit messages, and PR descriptions are treated as **untrusted input**.

Codentry is designed to defend against:

* Prompt injection
* Malicious repository content
* Unauthorized actions
* Webhook spoofing
* Replay attacks

The AI does **not** have authority to:

* Modify repository code
* Approve Pull Requests
* Merge Pull Requests

---

# 🏗️ Architecture

Codentry uses a monorepo architecture.

```text
codentry/
│
├── apps/
│   └── web/                  # Next.js application
│
├── services/
│   └── ai-review/            # FastAPI review service
│
├── packages/
│   └── schemas/              # Shared review contracts
│
├── supabase/
│   └── migrations/           # Database migrations
│
├── docs/                     # Architecture & deployment docs
│
└── .github/
    └── workflows/            # CI/CD
```

### Current stack

| Layer               | Technology            |
| ------------------- | --------------------- |
| Frontend / Webhooks | Next.js               |
| Frontend Language   | TypeScript            |
| Backend             | FastAPI               |
| Backend Language    | Python                |
| Database            | PostgreSQL / Supabase |
| Vector Search       | pgvector              |
| Static Analysis     | ESLint, Semgrep       |
| AI                  | Claude API            |
| GitHub Integration  | GitHub App            |
| Frontend Hosting    | Vercel                |
| Backend Hosting     | Render                |
| Testing             | Vitest/Jest + Pytest  |
| CI                  | GitHub Actions        |

---

# 🔄 Review Pipeline

The planned review pipeline is:

```text
1. Developer creates Pull Request
                │
                ▼
2. GitHub sends webhook
                │
                ▼
3. Codentry verifies webhook
                │
                ▼
4. Review run is created
                │
                ▼
5. Pull Request diff is collected
                │
                ├───────────────┐
                ▼               ▼
          ESLint            Semgrep
                │               │
                └───────┬───────┘
                        ▼
                 Static Findings
                        │
                        ▼
                 Claude AI Review
                        │
                        ▼
                Finding Normalizer
                        │
                        ▼
              GitHub PR Comments
```

The static and AI findings remain independently identifiable so that their performance can be evaluated separately.

---

# 🧪 Research Component

Codentry is not only an engineering project; it is also designed as an experimental platform for evaluating AI-assisted code review.

The project investigates questions such as:

### Static vs AI vs Combined

How does review quality differ between:

```text
Static-only
     vs
AI-only
     vs
Static + AI
```

### Diff-only vs Context-aware Review

Does providing relevant repository context improve AI review quality?

### Retrieval

How does retrieval quality and `top-k` selection affect review performance?

### Finding Independence

How much overlap exists between deterministic static-analysis findings and AI-generated findings?

### Human vs AI-Generated Pull Requests

How do review results differ when evaluating human-authored and AI-generated code?

---

# 📊 Evaluation

Codentry does not rely on a single "accuracy" number.

The evaluation framework is intended to measure metrics such as:

* Precision
* Recall
* False-positive rate
* Issue coverage
* Finding location accuracy
* Confidence calibration
* Finding overlap
* Finding independence

This allows the project to evaluate whether combining static analysis and AI actually improves Pull Request review.

---

# 🔐 Security

Security is a core design requirement.

### GitHub Webhook Security

Incoming GitHub webhooks are verified using:

```text
HMAC-SHA256
```

with constant-time signature comparison.

### Replay Protection

GitHub delivery IDs are tracked so previously processed webhook requests cannot simply be replayed.

### Secrets

Secrets are stored through environment variables and deployment-platform secret management.

Sensitive values are never committed to Git or logged.

### AI Prompt Injection

Repository content is considered untrusted.

Codentry separates:

```text
System Instructions
        ↓
Review Instructions
        ↓
Untrusted Repository Content
        ↓
AI Output
```

Static analysis such as Semgrep can also help identify suspicious prompt-injection patterns.

---

# 📁 Project Status

### Phase 1 — Foundation ✅

Completed:

* Next.js application
* FastAPI service
* TypeScript strict mode
* Python configuration
* Structured JSON logging
* Shared review schema
* Supabase / pgvector infrastructure
* Health endpoints
* Automated tests
* CI pipeline
* Build verification
* Deployment configuration
* Vercel → Render network path
* Environment variable configuration

### Phase 2 — GitHub Integration ✅ (code) / ⚠️ (App registration pending)

Completed:

* Public webhook receiver with raw-body HMAC-SHA256 verification (constant-time compare)
* Durable, DB-backed replay protection (`webhook_deliveries`, unique on `delivery_id`)
* Authenticated Vercel → Render internal handoff (`X-Codentry-Internal-Secret`, distinct from the GitHub webhook secret)
* Installation / repository / pull-request bookkeeping, with repository activation (`is_active`)
* Async pipeline: `review_runs` goes `pending → running → completed`/`failed` — the original 0-findings placeholder was replaced in Phase 3 by the real static-analysis pipeline below
* GitHub App JWT + installation-token authentication module (implemented, unit-tested; used since Phase 3 to fetch PR file content)
* Internal review-run status endpoint, internal installations debug view, public setup/info page
* 39 backend tests + 26 frontend tests, all green; verified end-to-end locally with real HMAC signatures against both services actually running

Not yet done — **USER ACTION REQUIRED**: no real GitHub App has been
registered (needs an account with GitHub admin access). See
`docs/github-app-setup.md` for the exact configuration and
`docs/staging-test-phase2.md` for the staging verification procedure once
it exists.

### Phase 3 — Static Analysis ✅

Completed:

* Standalone pipeline (`services/ai-review/analysis/`) — zero AI/GitHub/Supabase calls, structurally verified by a subprocess test that blocks those imports and asserts the CLI still works
* Real ESLint (pinned baseline install + repo-config fallback) and Semgrep (local ruleset, no network) execution
* Finding normalization into the shared `Finding` schema (`packages/schemas/review.schema.json`, fixed the `file`→`file_path` naming mismatch left over from Phase 1)
* `findings` table (Phase 3 migration), wired into the real review-run lifecycle (`app/review_runner.py::run_static_review`)
* Standalone CLI: `python -m analysis.run <repo> <files>` — see `docs/static-analysis.md`
* 90+ backend tests total, including golden-output, timeout, partial-failure, and performance-baseline tests

Not yet done: `analysis/changed_files.py` (GitHub content fetching) is
tested only against mocked HTTP — no live GitHub App exists yet to verify
it against a real PR (same USER ACTION REQUIRED as Phase 2).

### Phase 4 — AI Review

Planned:

* Claude API integration
* Structured AI output
* Semantic review
* Correctness analysis
* Security reasoning
* Context-aware review

### Future Research Phases

* Repository-level RAG
* pgvector retrieval
* Evaluation harness
* Benchmark datasets
* Human vs AI-generated PR experiments
* Retrieval experiments
* Optional multi-agent architecture

---

# 🌐 Language Support

The **MVP focuses on JavaScript and TypeScript**.

However, the internal architecture is intended to remain language-agnostic.

Future analyzers could follow an adapter model:

```text
                 Codentry
                    │
             Language Detector
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   JavaScript     Python       Java
        │           │           │
     ESLint       Ruff       Checkstyle
     Semgrep      Semgrep      Semgrep
        │           │           │
        └───────────┼───────────┘
                    ▼
             Unified Findings
                    │
                    ▼
                 Claude
```

The goal is to avoid making the core review pipeline dependent on a single programming language.

---

# 🛠️ Development

## Prerequisites

Install:

* Node.js
* npm
* Python 3.x
* Git

You will also need credentials for the services used by the project when running the complete system.

---

## Clone

```bash
git clone https://github.com/rushikeshmalgan/codentry.git
cd codentry
```

---

## Frontend

```bash
cd apps/web
npm install
npm run dev
```

The Next.js application runs locally using the development server.

---

## Backend

```bash
cd services/ai-review

python -m venv .venv
```

### Windows

```powershell
.venv\Scripts\Activate.ps1
```

Then:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

# 🧪 Testing

Frontend checks:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Backend checks:

```bash
ruff check .
pytest
```

All checks are also executed through GitHub Actions for Pull Requests.

---

# 🔧 Environment Variables

Environment variables should be configured using the appropriate `.env` files locally and deployment-platform secrets in production.

An `.env.example` file is provided as a reference.

**Never commit real credentials or private keys.**

---

# 📌 Project Principles

Codentry follows several important architectural principles:

### 1. GitHub-native

The developer should be able to use Codentry primarily from the Pull Request itself.

### 2. Deterministic + AI

AI should complement static analysis rather than replace it.

### 3. Evidence-based evaluation

Every review finding should be traceable to its source and evaluated independently.

### 4. Minimal AI authority

Claude provides review reasoning but does not modify, approve, or merge code.

### 5. Security first

Repository content is untrusted input.

### 6. Research-ready architecture

The system should make it possible to compare different review strategies experimentally.

### 7. Avoid premature complexity

RAG, multi-agent systems, advanced retrieval, and other research features are introduced only after the MVP pipeline is stable.

---

# 👥 Team

**Codentry** is being developed as a final-year engineering project.

The project combines:

* Full-stack development
* Backend engineering
* GitHub API integration
* Static code analysis
* Generative AI
* Information retrieval
* Software security
* Empirical evaluation

---

# 🎯 Vision

Codentry aims to explore a practical question:

> **Can combining deterministic static analysis with context-aware AI reasoning produce more useful and reliable GitHub Pull Request reviews than either approach alone?**

The goal is not to replace developers or human code reviewers.

Instead, Codentry aims to provide developers with **fast, contextual, actionable feedback directly where code changes are reviewed — the GitHub Pull Request.**
