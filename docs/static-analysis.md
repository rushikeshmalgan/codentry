# Static analysis (Phase 3)

`services/ai-review/analysis/` is a standalone, deterministic static-analysis
pipeline: ESLint + Semgrep, normalized into the shared `Finding` shape
(`packages/schemas/review.schema.json`). It has zero AI, GitHub, or Supabase
dependency — see "Zero-AI verification" below for how that's actually
checked, not just asserted.

## Standalone usage

```bash
cd services/ai-review
python -m analysis.run <repo_path> <file1> [file2 ...]
```

Example, using the fixtures checked into this repo:

```bash
python -m analysis.run analysis/fixtures eslint_sample.js semgrep_sample.js
```

Prints a JSON report to stdout and exits `0` (analysis ran; findings may or
may not be present — a partial tool failure with the other tool still
succeeding is still exit `0`, visible as `"overall_status": "partial_failure"`)
or `2` (both tools failed/were unavailable — nothing was analyzed).

## Required tools

- **Node.js** (`node` must be on `PATH`) + the pinned ESLint install at
  `analysis/eslint-baseline/` (run `npm install` there once — it has its own
  `package.json`, separate from `apps/web`'s).
- **Semgrep** — `pip install semgrep` (already in `requirements.txt`).
  Confirmed to install and run correctly on Windows as well as Linux/macOS.

Neither is required to *import* `analysis.run` or `analysis.static_analysis`
— only to actually get findings back instead of an `"error"` tool status.

## Architecture

```
changed files (local disk, or GitHub content via analysis/changed_files.py)
        |
        v
  ephemeral workspace (analysis/workspace.py) — fresh temp dir per run,
  always deleted, even on failure
        |
        +-------------------+
        |                   |
        v                   v
      ESLint              Semgrep
  (eslint_runner.py)   (semgrep_runner.py)
        |                   |
        +-------------------+
                |
                v
        normalize.py -> Finding[]
        (packages/schemas/review.schema.json's Python mirror,
         analysis/finding.py)
```

`analysis/static_analysis.py::run_static_analysis(repo_path, changed_files)`
is the FR-2 entry point. It never imports `app.*`, `supabase`, `jwt`,
`anthropic`, `openai`, or `httpx` — the one deliberate exception is
`analysis/changed_files.py`, which fetches PR content from GitHub via
Phase 2's `app.github_auth` (reusing that auth rather than inventing a
second one) and is imported only by `app/review_runner.py`, never by
`analysis/run.py`.

## Security model

- Source code is **data**, never executed. It's written to a temp file and
  handed to ESLint/Semgrep as a path to read text from.
- **Ephemeral workspace**: a fresh `tempfile.mkdtemp()` per run, containing
  only the files actually being analyzed, deleted on every exit path
  (success, exception, or timeout) via a context manager.
- **Timeouts**: 30s per tool (`ESLINT_TIMEOUT_SECONDS`, `SEMGREP_TIMEOUT_SECONDS`),
  enforced via `subprocess.run(..., timeout=...)`. A timeout is recorded as
  a tool status, not raised as an unhandled exception — the other tool's
  results (if it succeeded) are still kept.
- **File limits**: max 200 files, max 500 KB per file
  (`analysis/workspace.py::MAX_FILES` / `MAX_FILE_SIZE_BYTES`) — exceeding
  either raises `WorkspaceLimitError` before anything is written to disk.
- **No `shell=True` anywhere**: every subprocess call passes an explicit
  argument list. ESLint is invoked as `node <eslint.js> ...args` rather than
  through the `node_modules/.bin/eslint` shim, specifically because that shim
  is a `.cmd` file on Windows and executing `.cmd` files via `subprocess`
  without a shell is unreliable — calling `node` directly with the script
  path as a plain argument sidesteps that entirely, on every OS.
- **No network required**: Semgrep uses only the local ruleset file
  (`analysis/semgrep-rules/baseline.yml`) — deliberately not a Semgrep
  Registry pack (`--config p/security-audit`), which fetches rules over the
  network on first use. ESLint needs no network at all. Both were run in
  this environment with no special network configuration and produced
  identical results run to run (see determinism note below).
- **Repository-provided config never triggers untrusted installs**: a
  repo's own `.eslintrc.*` is honored only if it *loads* successfully
  against Codentry's pinned baseline plugin set
  (`--resolve-plugins-relative-to analysis/eslint-baseline`). A config
  referencing a plugin outside that set fails to load and falls back to the
  baseline config — Codentry never runs `npm install` against repository
  content, which would mean executing arbitrary, untrusted install scripts.

## Failure behavior

`StaticAnalysisResult.overall_status` (`analysis/static_analysis.py`) is one
of:

- **`completed`** — both tools ran (or were correctly skipped, e.g. no
  analyzable files).
- **`partial_failure`** — exactly one tool failed/timed out/was unavailable;
  findings from the tool that *did* run are still returned and persisted.
  Maps to `review_runs.status = 'completed'` in the database, with the
  failure surfaced via `error_message` rather than hidden — a partial
  result is not silently reported as a full success, but it's also not
  discarded.
- **`failed`** — both tools failed. Maps to `review_runs.status = 'failed'`.
  No findings are persisted (there are none).

The same three-way distinction applies to the changed-files fetch itself: if
GitHub can't be reached or the App isn't configured, the review run is
marked `failed` with a specific `error_message`
(`github_app_not_configured` or `changed_files_fetch_failed: ...`) rather
than hanging or silently reporting zero findings as if nothing were wrong.

## Configuration

- **ESLint priority**: (1) a repository-provided `.eslintrc.json` /
  `.eslintrc.js` / `.eslintrc.yml` / `.eslintrc.yaml` / `.eslintrc` at the
  workspace root, if it loads successfully; (2) Codentry's baseline
  (`analysis/eslint-baseline/.eslintrc.baseline.json` — `eslint:recommended`
  plus `@typescript-eslint/recommended` for `.ts`/`.tsx` files).
- **Semgrep ruleset**: `analysis/semgrep-rules/baseline.yml` — three rules
  (`hardcoded-secret`, `eval-usage`, `sql-string-concatenation`), all
  `category: security`. Extending this file is how Phase 6+ would add more
  patterns; no code changes needed for a new rule.

## Zero-AI verification

`tests/test_analysis_cli.py::test_cli_makes_zero_ai_github_supabase_calls`
runs the actual CLI as a subprocess with a Python meta-path import blocker
that raises `ImportError` the instant anything tries to import `supabase`,
`jwt`, `anthropic`, `openai`, `httpx`, `postgrest`, `gotrue`, or `app` — and
asserts the CLI still completes successfully with real findings. This is a
structural, executed proof, re-checked on every test run, not a comment
asserting it once and hoping it stays true.

## Known limitations

- `analysis/changed_files.py` is tested only against a mocked HTTP
  transport (respx) — no live GitHub App exists in this environment to
  verify it against real PR data. See `docs/github-app-setup.md` and
  `docs/staging-test-phase2.md`.
- The Semgrep baseline ruleset covers three patterns, chosen to match the
  Phase 3 spec's minimum fixture requirements. It is not a comprehensive
  security ruleset — expanding it is expected in a later phase, not
  something this phase claims to have done.
- Performance numbers in `tests/test_analysis_performance.py` are a dev-box
  baseline (one machine, cold subprocess starts each time), not a
  production latency claim — Phase 7 measures that for real.
