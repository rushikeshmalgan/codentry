# Codentry Semgrep ruleset

`production.yml` is the only ruleset the analysis pipeline loads.

## What this is — and is not

- It is **six hand-written rules** (`hardcoded-secret`, `eval-usage`,
  `new-function-usage`, `child-process-exec-non-literal`,
  `sql-string-concatenation`, `innerhtml-assignment`) for JavaScript/TypeScript.
- It is **not** Semgrep's registry coverage (`p/security-audit`, `p/owasp-top-ten`,
  ...). Those packs are network-fetched, versioned externally, and hundreds of
  rules; running them is an explicit non-goal until the evaluation harness can
  pin them reproducibly.
- Any evaluation result must therefore be labeled **"Codentry baseline
  ruleset (6 rules) run with Semgrep {version}"**, never "Semgrep's precision"
  or "Semgrep's recall". A weak ruleset makes the static arm look bad for
  reasons that have nothing to do with static analysis in general.

## Rules of the road

1. Production rules live only in `production.yml`. Toy or experimental rules
   used to exercise the pipeline live under `tests/` and are never loaded by
   the service.
2. Every rule needs a true-positive test **and** a false-positive-guard test
   (`tests/test_semgrep_ruleset.py`).
3. `sql-string-concatenation` only fires when the left-hand literal *looks like*
   SQL (`SELECT`/`INSERT INTO`/`UPDATE`/`DELETE FROM`). The Phase 3 version
   matched any `"..." + x`, which flagged ordinary string building.
4. Known coverage gaps (not yet detected): template-literal SQL, taint flow
   across functions/files, framework-specific sinks, secrets in non-assignment
   positions (object literals, function arguments).
5. Changing this file changes the evaluation baseline. The pipeline records the
   file's SHA-256 in every run's `analysis_meta.ruleset_sha256`.
