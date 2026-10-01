# Demo script — 10 minutes

**Status: drafted, not yet rehearsed.** Day 7's acceptance criterion ("two full demo
rehearsals without an unplanned intervention") is the team's to meet; this script is
what to rehearse. Fill in the exact report filename once Day 4's full run has produced
one (see `evaluation/reports/`), and the Track G row once/if it is run
(`docs/REAL_RUN_LOG.md`).

## Before the room: warm-up checklist

- [ ] `evaluation/reports/<date>-arm-a.md` exists and `python -m evaluation.repro` passes
      against it (command in `evaluation/README.md`).
- [ ] `PYTHONPATH=services/ai-review python -m pytest services/ai-review/tests` and
      `python -m pytest evaluation/tests` are green locally.
- [ ] If presenting the real pipeline live: the Render service is warmed (hit
      `/api/status` once — cold start can exceed GitHub's 10-second webhook timeout).
      Otherwise: say up front that the walkthrough uses the **local, mocked-GitHub**
      pipeline (`services/ai-review/tests/test_review_runner.py` and friends), and label
      it that way on screen, not just verbally.
- [ ] The backup screen recording (below) is loaded and ready as a fallback.

## (a) A pull request becomes `new` vs `existing` findings — 3 min

1. Show the architecture diagram (`docs/architecture.md` §7 / `docs/PROJECT_STATUS.md`
   §7): webhook → durable job → pinned snapshot → differential analysis → finalize.
2. Walk one case from `evaluation/cases/` end to end (a `mut-*` case is easiest to narrate:
   one file, one seeded edit) — show `base/` and `head/`, then
   `evaluation/<case-id>/result.json`'s `findings` list, pointing at one finding with
   `"change_status": "new"` and one (if present) `"existing"`. Say explicitly: *existing*
   findings are pre-existing code the pull request did not introduce and Codentry never
   blames it for.
3. If real Track G evidence exists (`docs/REAL_RUN_LOG.md`), show the actual GitHub PR
   and the row in `review_runs`. **If it does not**, say so in one sentence and move on —
   do not imply a live run that did not happen.

## (b) The harness report and its limitations — 3 min

1. Open `evaluation/reports/<date>-arm-a.md`. Point at:
   - the per-stratum tables (mutation logic, rule-aligned injections, real defects,
     noise pull requests) and that **they are never pooled into one number**;
   - one Wilson interval, read aloud with its width (small-N honesty is the point);
   - the **"Not measured"** section — precision and false positives per pull request are
     not estimated because nobody has adjudicated findings yet.
2. Say the headline finding plainly: a six-rule static arm has **low recall** on seeded
   logic mutants and real bugs, and that is an expected, reported result, not a failure
   of the harness (plan Day 4: "a 0/20 result would still bound recall below 0.161").

## (c) Identity stability — 2 min

1. Open the identity-stability section of the report. Explain the question in one
   sentence: *if a pull request only shifts lines or changes whitespace, does Codentry
   still recognize the same finding as the same finding?*
2. Show one real example: the same `identity_key` before and after a transformation, and
   why that matters for differential analysis (new findings should mean new *problems*,
   not new *line numbers*).

## (d) The security fixes, proven failing before and passing after — 2 min

1. Run (or show the recorded output of) the Phase 0 proof-of-concept tests, e.g.
   `services/ai-review/tests/test_security_poc.py`, and say: *these asserted a real
   exploit against the old code, confirmed failing, then passing after the fix* — not
   "we added input validation", but a demonstrated before/after.
2. One sentence on what changed: PR-supplied ESLint config is no longer trusted; secrets
   are scrubbed from the analysis subprocess environment; findings are identified by
   content, not line number, so they survive unrelated edits.

## If something breaks live

Switch to the backup recording immediately — do not debug on stage. Say which step
failed and that the recording shows the same path. The report and test suites are frozen
artifacts (Day 7 task 2); nothing about the demo depends on a live network call succeeding.

## Backup recording

- [ ] Recorded (date: ______). Location: ______.
