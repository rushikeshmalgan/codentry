# Static analysis (Phase 3, hardened in Phase 0)

`services/ai-review/analysis/` is a standalone, deterministic static-analysis
pipeline: ESLint + Semgrep, normalized into the shared `Finding` shape
(`packages/schemas/review.schema.json`). It has zero AI, GitHub, or Supabase
dependency (except `analysis/changed_files.py`, see below) — "Zero-AI
verification" below shows how that is checked, not just asserted.

For the system around it (jobs, events, differential flow) see
[`architecture.md`](architecture.md).

## Standalone usage

```bash
cd services/ai-review
python -m analysis.run <repo_path> <file1> [file2 ...]
```

```bash
python -m analysis.run analysis/fixtures eslint_sample.js semgrep_sample.js
```

Prints a JSON report and exits `0` (analysis ran; a one-tool failure is still
`0`, visible as `"overall_status": "partial_failure"`) or `2` (both tools failed).
The CLI is **not** differential: it analyzes the files as given, so its findings
carry `change_status = null` ("not classified against a base").

## Required tools

- **Node.js** on `PATH` + the pinned ESLint install at `analysis/eslint-baseline/`
  (`npm install` there once; separate `package.json` from `apps/web`).
- **Semgrep** — `pip install semgrep` (in `requirements.txt`). The runner looks in
  the interpreter's own scripts directory first, so a service started as
  `venv/bin/uvicorn` finds its Semgrep even when the venv is not on `PATH`.

## Pipeline

```
files (local disk, or a pinned GitHub snapshot)
   |  prepare_files: drop unsafe paths / control files / non-analyzable types /
   |                 oversize files / duplicates — each with a recorded reason
   v
ephemeral workspace + tool sandbox (temp HOME/TEMP/config, outside the workspace)
   |
   +--> ESLint  (baseline [+ sanitized base overlay], no inline config, no ignore files)
   +--> Semgrep (local production ruleset, --disable-nosem, resource ceilings)
   v
normalize (secrets redacted) -> Finding[]  -> identity v2 (line-independent)
```

## Security model (verified by `tests/test_security_poc.py`)

Repository content is hostile. Every claim below has an executable test; the
"before" column is what the unmodified Phase 3 code did when those same tests
were run against it.

| Threat | Phase 3 behavior (verified by running the PoC against it) | Now |
|---|---|---|
| PR ships `.eslintrc.js` | **Executed** by ESLint | Never written or loaded |
| PR ships `.eslintrc.json` with `parser`/`extends` pointing at its own JS | **`require()`d** | Never written or loaded |
| Server secrets in the subprocess environment | ESLint got `os.environ` wholesale; Semgrep inherited it | Allowlisted env only; secrets absent (a real `node` child is checked) |
| File named `--bogus.js` | Parsed as a CLI option; the tool errored and the file's findings **vanished** | `--` terminator + `./` prefix |
| Drive-absolute path (`C:/…`) | `materialize()` **wrote outside the workspace** (a file appeared in `C:\Windows\Temp`) | Rejected |
| `..`, backslashes, UNC, NUL, `C:x` | Already rejected by exception, except `C:x` (accepted, but stayed inside the workspace) | All rejected; the pipeline skips and records them instead of failing the whole run |
| `.eslintignore` / `/* eslint-disable */` / `// nosemgrep` | Hid findings (`.semgrepignore` did not hide explicit files) | Ignored (`--no-ignore`, `--no-inline-config`, `--disable-nosem`) |
| PR turns rules off via its own config | Honored | Baseline decides |
| Symlink in a checkout (CLI) | Followed | Skipped (`symlink_or_special`) |
| Secret echoed in a tool message / error snippet | Stored verbatim | Redacted (`analysis/redact.py`) |

Additional controls: no `shell=True` anywhere; ESLint invoked as
`node eslint.js` (not the `.cmd` shim); process tree killed on timeout; output
size cap; `--max-memory`, `--timeout`, `--max-target-bytes` for Semgrep and
`--max-old-space-size` for Node; files written as raw bytes so line numbers match
git; no network required (local ruleset only).

**Not a sandbox.** See `architecture.md` → known gaps #2.

Verified by source inspection vs. by running (be precise about which):
- ESLint executes `.eslintrc.js` / loads `parser` from a repo config —
  *source inspection* of ESLint's loader **and** *executed PoC* (the PoC
  tests failed against the Phase 3 code and pass now).
- The `--parser=./evil.js` option-smuggling path — *source inspection only* on
  this Windows machine (the PoC needs a POSIX directory name); it runs in CI.

## Configuration policy

**Nothing from the PR under review configures the analysis.**

- ESLint: `analysis/eslint-baseline/.eslintrc.baseline.json` (`eslint:recommended`
  plus `@typescript-eslint/recommended` for TS), optionally overlaid by a
  **sanitized** `.eslintrc.json` read from the trusted **base commit**
  (`analysis/trusted_config.py`). The overlay may add `rules`, `env`, `globals`
  only, each validated (plugin rules, unknown envs, bad severities are dropped
  and recorded). Never `parser`, `plugins`, `extends`, `processor`, `overrides`,
  `.js`, or YAML. Written to a temp file **outside** the workspace.
  **This removes a Phase 3 feature** (honoring a repo's own config) on security
  grounds.
- Semgrep: `analysis/semgrep-rules/production.yml` — six hand-written rules
  (`hardcoded-secret`, `eval-usage`, `new-function-usage`,
  `child-process-exec-non-literal`, `sql-string-concatenation`,
  `innerhtml-assignment`). Toy rules do not live there; see
  `analysis/semgrep-rules/README.md`. The SQL rule now requires a SQL-looking
  literal (the Phase 3 one matched any `"..." + x`).

## Failure behavior

`StaticAnalysisResult.overall_status`: `completed` (both tools ran or were
correctly skipped), `partial_failure` (one failed), `failed` (both failed).
`analysis_complete` is stricter: it also requires that nothing that should have
been analyzed was skipped (`too_large`, `unsafe_path`, `tool_error`,
`fetch_failed`, `base_unavailable`, …). Skipping a README, lockfile, or control
file is *not* incompleteness.

In the review pipeline (`app/review_runner.py`) these map to
`review_runs.status`: `completed` only when complete; **`partial`** when a tool
failed, a file was skipped, or the differential could not cover everything;
`failed` when the head analysis failed outright or the snapshot could not be
built (`too_many_files`, `not_found`, `auth`, …). Phase 3 reported a one-tool
failure as `completed`; that hid data loss.

## Finding identity and differential analysis

See `architecture.md`. In short: `identity_key` is content-anchored and does not
depend on line numbers; `dedup_hash` adds an occurrence index; the review
pipeline classifies head findings against the merge base as `new` / `existing`
(`moved`) / `fixed`.

## Zero-AI verification

`tests/test_analysis_cli.py::test_cli_makes_zero_ai_github_supabase_calls`
runs the real CLI in a subprocess with an import blocker that raises
`ImportError` for `supabase`, `jwt`, `anthropic`, `openai`, `httpx`,
`postgrest`, `gotrue`, and `app`. `tests/test_scope_guards.py` additionally
scans all production code for AI SDK imports, LLM endpoints, and prompt
machinery.

## Known limitations

- `analysis/changed_files.py` is tested only against mocked HTTP (respx +
  `tests/fake_github.py`); no live GitHub App exists here.
- The Semgrep ruleset is small and hand-written. It does not detect
  template-literal SQL, cross-function taint, or framework-specific sinks.
- ESLint parse errors surface as `eslint-fatal-error` findings (a real signal,
  but a different kind of signal from a rule violation; evaluation should
  separate them).
- Performance numbers in `tests/test_analysis_performance.py` are a dev-box
  baseline, not a production latency claim.
