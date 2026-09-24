# Phase 0 hardening report — evidence

Companion to the completion report. This file records the executable evidence;
[`architecture.md`](architecture.md) describes the resulting design and its known gaps.

## How claims are labeled

- **Executed PoC** — a test in `services/ai-review/tests/test_security_poc.py`
  that was run against the *unmodified Phase 3 code* (it failed) and against the
  fixed code (it passes). Harmless payloads only: marker files under pytest's
  `tmp_path`, or canary environment variables created by the test.
- **Source inspection** — read from the code (ours or ESLint's), not executed.
- **Mocked** — exercised against a fake (respx GitHub, in-memory store). Not
  evidence about the real service.
- **Not verified** — could not be run here.

## Findings: before vs after

Before-fix run: `29 failed, 3 passed, 1 skipped` (33 PoC tests, Phase 3 code,
Windows, Semgrep on PATH). Read that number carefully:

- **22 of the 29 failures demonstrate a real defect** (3 config-execution PoCs,
  1 secret leak, 1 option-parsing failure, 1 arbitrary write outside the
  workspace, 12 control files written, 4 finding-hiding/rule-override cases).
- **6 failures were an artifact of my first test's shape, not vulnerabilities:**
  the Phase 3 code already *rejected* `../x.js`, `a/../../x.js`, a backslash
  `..` path, `/abs/x.js`, a UNC path, and a NUL path by raising
  `WorkspaceLimitError` (or `ValueError`), and the first version of the test
  asserted "no exception".
- **1 failure was harmless:** `C:escape.js` was accepted but landed *inside* the
  workspace.
- **Of the 3 that passed, two hid a real bug** (drive-absolute `C:/...` paths:
  the unmodified code wrote `C:/Windows/Temp/escape.js`; my first assertion only
  looked inside the workspace, so it passed. The test was corrected and the
  stray file deleted) and one was genuinely non-exploitable (`.semgrepignore`).

| # | Issue | Severity | Evidence | Before (Phase 3) | After |
|---|---|---|---|---|---|
| 1 | Repo `.eslintrc.js` executed | Critical | **Executed PoC** + source (`@eslint/eslintrc` `importFresh`) | Marker file written by PR code | Not executed |
| 2 | Repo JSON config `parser` `require()`d | Critical | **Executed PoC** + source (`_loadParser`) | Marker written | Not loaded |
| 3 | Repo config `extends: ./x.js` executed | Critical | **Executed PoC** | Marker written | Not loaded |
| 4 | Server secrets visible to repo-controlled code | Critical | **Executed PoC** (canary env vars) + `test_a_real_child_process_cannot_see_server_secrets` (real `node` child) | `process.env` dump contained canaries | Absent |
| 5 | Filename `--bogus.js` parsed as an option → tool error → findings vanish | High | **Executed PoC** (ESLint: `Invalid option '--bogus-option'`; Semgrep: `unknown option '--bogus-option.js'`) | Both tools failed | Analyzed normally |
| 6 | Option smuggling `--parser=./evil.js` | High | **Source inspection only on this machine** (needs a POSIX dir named `--parser=.`); PoC written, skipped on Windows, **runs in CI on Ubuntu (not yet run)** | n/a here | Structurally prevented (`--` + `./`), argv asserted in unit tests |
| 7 | Absolute drive path writes outside workspace | High | **Executed PoC** — the unmodified `materialize()` wrote `C:/Windows/Temp/escape.js` (file deleted afterwards); found while re-checking why two cases "passed" before the fix | File written outside workspace | Rejected |
| 8 | `..`, backslash, UNC, `C:x`, NUL paths | Low | **Executed PoC** | `..`, leading `/`, UNC, NUL were **already rejected** (by exception); `C:x` accepted but stayed inside the workspace | All rejected; unsafe files are skipped and recorded, never fatal |
| 9 | Control files written into the workspace (`.eslintrc*`, `.eslintignore`, `.semgrepignore`, `package.json`, …) | High | **Executed PoC** (12 names) | Written | Never written |
| 10 | `.eslintignore` hides findings | High | **Executed PoC** | Findings hidden | Reported |
| 11 | `/* eslint-disable */` hides findings | High | **Executed PoC** | Hidden | Reported |
| 12 | `// nosemgrep` hides findings | High | **Executed PoC** | Hidden | Reported |
| 13 | `.semgrepignore` hides findings | — | **Executed PoC**: *not exploitable* for explicitly-passed files | Passed already | Still passes; file no longer written |
| 14 | PR config turns off baseline rules | High | **Executed PoC** | Honored | Ignored |
| 15 | Events lost after a failure (delivery recorded before processing) | High | Source inspection + tests of the new state machine (`test_failure_after_claiming_leaves_the_delivery_retryable_and_a_redelivery_succeeds`) — the *old* behavior was not re-run | Retry treated as duplicate | Reclaimed |
| 16 | Review as a non-durable `BackgroundTask`; runs stuck `running` | High | Source inspection + new lease/crash-recovery tests (in-memory store) | Lost on restart | Row-based job, lease, bounded attempts |
| 17 | Not pinned to the event's commit; silent single-page truncation | High | Source inspection + mocked pagination/pinning tests | 1 page of 100; unpinned | `Link`-paginated, count-checked, all reads `?ref=<sha>` |
| 18 | Whole-file analysis blamed PRs for pre-existing findings | High | Mocked + real ESLint/Semgrep differential tests | All findings reported | new / existing / fixed |
| 19 | Finding identity changed with line numbers | Medium | Unit tests (`tests/test_identity.py`) | Line-based hash | Content-anchored |
| 20 | Production silently used volatile in-memory store | Medium | Tests (`tests/test_production_hardening.py`) incl. real subprocess for docs-off | Warn and continue | Refuses to start |
| 21 | `/internal/installations` unauthenticated; public error text leaked backend URL/errors | Medium | **Executed against a real `next start`**: default 404 (even with credentials), 401 without/with wrong auth, 200 with correct auth; `/api/status` returned only `unreachable`, detail only in server log | Open / leaking | Gated / generic |
| 22 | FastAPI `/docs`, `/openapi.json` on in production | Low | Executed (subprocess with `ENVIRONMENT=production`) | Enabled | `None None None` |
| 23 | Toy Semgrep rules (`"..." + x` matched any concatenation) presented as Semgrep | Research validity | Real Semgrep TP/FP tests | 3 rules, 1 noisy | 6 rules with FP guards, honest labeling |
| 24 | Docs/setup page claimed AI review and PR comments | Medium | Read | Overclaimed | Corrected |

## Migration verification

`supabase/migrations/0001…0004` were **syntax-parsed** with `sqlglot`
(dialect `postgres`): all parsed. They have **not been executed** against
Postgres; semantic errors (e.g. a constraint conflicting with existing rows)
are possible.

## Real GitHub verification

**None.** No GitHub App, Supabase project, Render service, or Vercel
deployment exists in this environment. `tests/test_e2e_local_mocked.py` is a
local, mocked-GitHub run with real ESLint and Semgrep; it is labeled as such in
its docstring and must not be cited as real end-to-end verification.

## Test commands and actual results (final run, Windows 11, Python 3.13.7, Node 22.14.0, Semgrep 1.177.0)

| Command | Result |
|---|---|
| `cd services/ai-review && python -m pytest` | **388 passed, 1 skipped, 0 failed** (457.9 s). The skip is the POSIX-only option-smuggling PoC. Before Phase 0: 102 backend tests. |
| `python -m pytest tests/test_security_poc.py` | 32 passed, 1 skipped. Against the unmodified Phase 3 code the (then 33-test) file gave 29 failed / 3 passed / 1 skipped. |
| `ruff check .` (services/ai-review) | All checks passed |
| `cd apps/web && npm run test` | 6 files, **38 passed** (was 26) |
| `npm run typecheck` / `npm run lint` / `npm run build` | clean / no warnings / success (middleware compiled: 34.7 kB) |
| Real `next start` on ports 3055-3057 (manual, curl) | default: `/internal/installations` 404 even with credentials; `INTERNAL_PAGES_ENABLED=true`: 401 (+`WWW-Authenticate`) without auth, 401 wrong password, 200 correct; `/api/status` body exactly `{"web":"ok","backend":"unreachable"}`; detail only in the server log |
| `sqlglot.parse(..., read="postgres")` on migrations 0001-0004 | all parse (syntax only; **not executed**) |

Suite runtime is dominated by real ESLint/Semgrep subprocesses (each ESLint
start is 1-3 s). Nothing in the suite requires network access, a GitHub App,
or a database.
