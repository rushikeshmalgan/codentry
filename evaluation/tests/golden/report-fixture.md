# Arm A evaluation report — ESLint + Codentry baseline ruleset (6 rules) run with Semgrep 9.9.9

> **Read this first.** These are the first numbers this project has produced, from small public-code corpora, with a small hand-written ruleset. Strata answer different questions and are never combined; there is no overall score. Precision and false positives per pull request are **not estimated** (see *Not measured*). Every proportion shows its counts and a 95% Wilson interval.

## Provenance

- Arm: ESLint + Codentry baseline ruleset (6 rules) run with Semgrep 9.9.9 — reported findings are those with `change_status == 'new'`
- Cases: 11 (10 completed, 1 partial)
- Case set SHA-256: `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`
- Results SHA-256: `cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`
- Code commit: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
- Tools: eslint_version 8.0.0, semgrep_version 9.9.9, node_version v22.0.0, python_version 3.13.0; ruleset SHA-256 `dddddddddddddddd…`
- Default match tolerance k = 2 lines (sensitivity at k = 0, 5 shown alongside)

## Results by stratum

### Mutation-seeded logic defects (`mutant:logic`)

4 cases; 3 completed; **excluded (analysis incomplete): l4**. Metrics use completed cases only.

| Recall of known defects | detected / defects |
|---|---|
| k = 0 | 1/3 = 33.3% (95% CI 6.1%–79.2%) |
| k = 2 (headline) | 2/3 = 66.7% (95% CI 20.8%–93.9%) |
| k = 5 | 2/3 = 66.7% (95% CI 20.8%–93.9%) |

- Cases in which at least one defect was detected (k = 2): 2/3 = 66.7% (95% CI 20.8%–93.9%)
- Location accuracy of matched findings (share that overlap the defect exactly): 1/2 = 50.0% (95% CI 9.5%–90.5%)
- Findings matched to a known defect: 2; **unmatched: 1** (not adjudicated — not false positives)
- Reported (`new`) findings: 3 in 3 cases; mean 1.00 per case (95% bootstrap CI 0.00–2.00), median 1, max 2
- Reported findings per 100 changed lines: 13.04 (23 changed lines)
- Pre-existing share of findings on touched files (`existing` / (`new` + `existing`)): 0/3 = 0.0% (95% CI 0.0%–56.1%) — findings a naive whole-file review would have blamed on the change
- Duplicate rate among reported findings: 0/3 = 0.0% (95% CI 0.0%–56.1%)
- Analysis wall time per case (this machine): median 2.0 s, 90th percentile 3.0 s, max 3.0 s (n = 3)

### Rule-aligned injections (`mutant:rule-aligned`) — favorable to Arm A by construction

2 cases; 2 completed. Metrics use completed cases only.

| Recall of known defects | detected / defects |
|---|---|
| k = 0 | 2/2 = 100.0% (95% CI 34.2%–100.0%) |
| k = 2 (headline) | 2/2 = 100.0% (95% CI 34.2%–100.0%) |
| k = 5 | 2/2 = 100.0% (95% CI 34.2%–100.0%) |

- Cases in which at least one defect was detected (k = 2): 2/2 = 100.0% (95% CI 34.2%–100.0%)
- Location accuracy of matched findings (share that overlap the defect exactly): 2/2 = 100.0% (95% CI 34.2%–100.0%)
- Findings matched to a known defect: 2; **unmatched: 0** (not adjudicated — not false positives)
- Reported (`new`) findings: 2 in 2 cases; mean 1.00 per case (95% bootstrap CI 1.00–1.00), median 1, max 1
- Reported findings per 100 changed lines: 10.00 (20 changed lines)
- Pre-existing share of findings on touched files (`existing` / (`new` + `existing`)): 0/2 = 0.0% (95% CI 0.0%–65.8%) — findings a naive whole-file review would have blamed on the change
- Duplicate rate among reported findings: 0/2 = 0.0% (95% CI 0.0%–65.8%)
- Analysis wall time per case (this machine): median 5.0 s, 90th percentile 6.0 s, max 6.0 s (n = 2)

### Real defects, fixes reversed (`real:bugsjs`)

2 cases; 2 completed. Metrics use completed cases only.

| Recall of known defects | detected / defects |
|---|---|
| k = 0 | 1/2 = 50.0% (95% CI 9.5%–90.5%) |
| k = 2 (headline) | 1/2 = 50.0% (95% CI 9.5%–90.5%) |
| k = 5 | 1/2 = 50.0% (95% CI 9.5%–90.5%) |

- Cases in which at least one defect was detected (k = 2): 1/2 = 50.0% (95% CI 9.5%–90.5%)
- Location accuracy of matched findings (share that overlap the defect exactly): 1/1 = 100.0% (95% CI 20.7%–100.0%)
- Findings matched to a known defect: 1; **unmatched: 0** (not adjudicated — not false positives)
- Reported (`new`) findings: 1 in 2 cases; mean 0.50 per case (95% bootstrap CI 0.00–1.00), median 0, max 1
- Reported findings per 100 changed lines: 2.50 (40 changed lines)
- Pre-existing share of findings on touched files (`existing` / (`new` + `existing`)): 0/1 = 0.0% (95% CI 0.0%–79.3%) — findings a naive whole-file review would have blamed on the change
- Duplicate rate among reported findings: 0/1 = 0.0% (95% CI 0.0%–79.3%)
- Analysis wall time per case (this machine): median 7.0 s, 90th percentile 8.0 s, max 8.0 s (n = 2)

### Merged pull requests, no defect labels (`noise:pr`)

2 cases; 2 completed. Metrics use completed cases only.

- Reported (`new`) findings: 4 in 2 cases; mean 2.00 per case (95% bootstrap CI 0.00–4.00), median 0, max 4
- Reported findings per 100 changed lines: 4.00 (100 changed lines)
- Pre-existing share of findings on touched files (`existing` / (`new` + `existing`)): 8/12 = 66.7% (95% CI 39.1%–86.2%) — findings a naive whole-file review would have blamed on the change
- Duplicate rate among reported findings: 1/4 = 25.0% (95% CI 4.6%–69.9%)
- Analysis wall time per case (this machine): median 9.0 s, 90th percentile 10.0 s, max 10.0 s (n = 2)

### Excluded: harness self-test fixtures

`fx-1` test the harness, are hand-made, and are not evidence. They are not measured here.

## Not measured

- **Precision and false positives per pull request are not estimated.** They need two independent human labelers (evaluation/labeling/protocol.md); that step is open. Until then, "unmatched" above is a count of findings that hit no known defect — some may be real problems the ground truth does not list, and some hits may be coincidences.
- Anything about AI review: no AI arm exists.

## Limitations

1. **Arm A is a small hand-written ruleset.** It is ESLint with Codentry's baseline config plus six Semgrep rules; results say nothing about Semgrep's registry rules or about static analysis in general.
2. **Location-only matching.** A finding "hits" a defect if it overlaps the defect's lines (widened by k). It cannot tell whether the finding describes the defect, so a hit can be a coincidence, and a finding that points at the defect from elsewhere is scored unmatched. Recall is shown for k = 0, 2 and 5; read the k = 0 row too.
3. **Mutants are a proxy for real faults.** Equivalence is unchecked, so some mutants may not change behavior; mutation logic edits are mostly not the kind of defect a lint rule can see.
4. **The rule-aligned stratum is favorable to Arm A by construction:** each injected line is a pattern one of Arm A's six rules targets. It is reported apart and must never be pooled with the others.
5. **Real-defect cases are reversed fixes, not natural pull requests,** taken from a public benchmark; some have no recorded failing test and rest on the dataset's manual validation alone (evaluation/datasets/bugsjs.json says which).
6. **Contamination.** Every source is a public project a language model may have seen; this affects only future AI arms, but it constrains what these cases can show.
7. **Small, clustered samples.** Cases from the same file or project are not independent, so the Wilson intervals (which assume independent trials) are narrower than the true uncertainty.
8. **Noise pull requests are selected mechanically** from repository history (squash-merge commits), including trivial ones; they measure volume, not correctness.
9. **No adjudication has been done.** Precision and false positives per pull request need two independent human labelers; that step is open and is not estimated here.
10. **Tool timeouts are recorded, not hidden.** A case whose analysis did not complete is excluded from the metrics and listed; it is never scored as a clean run.

## Case lists (every number above is computed from exactly these cases)

- `fixture:new-and-existing` (1): `fx-1`
- `mutant:logic` (4): `l1`, `l2`, `l3`, `l4`
- `mutant:rule-aligned` (2): `r1`, `r2`
- `noise:pr` (2): `n1`, `n2`
- `real:bugsjs` (2): `b1`, `b2`
