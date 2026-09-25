# Labeling protocol — adjudicating static-analysis findings

**Status:** ready to use for the calibration round; nobody has labeled anything yet.
**Why this exists:** precision cannot be computed from unlabeled findings. A finding
that matches no known defect is *unmatched*, not *false*: it may be a real problem the
ground truth simply does not list (static warnings are notoriously hard to label — a
heuristic oracle disagreed with human oracles in the study behind survey ref [33]).
Only people reading the code can decide. This protocol makes those decisions
repeatable and lets us report how much the people agreed.

## Rules that are not negotiable

1. **Never a model.** No language model labels, pre-labels, suggests a label, or
   "double-checks" a label — for any arm, ever. A model judging a model's output
   would correlate errors and flatter the AI arm (survey refs [43]–[45]).
2. **Two independent labelers** per item. "Independent" means: each fills in their own
   file, in their own time, and does not see the other's labels or discuss the items
   until both have finished the whole round.
3. **Blind to the arm.** The sheet shows the tool's rule and message (you need them to
   understand the claim) but not which arm or run produced it, not any score, severity
   or confidence, and not whether the tool calls the finding new or pre-existing. Items
   are in a fixed pseudo-random order; do not reorder them.
4. **Record everything that changed the decision.** If you looked at anything beyond the
   sheet (the project's docs, its later history, a search), write it in `note`.

## What you are shown

One item = one finding: the file and line range, the tool, the rule id and its message,
and the code around it (about eight lines either side, the flagged lines marked `>`).
That is normally enough. If it is not, that is itself information: see `unclear`.

## The question you answer

> Is this a real problem **in the code as it is written here** — something a reasonable
> maintainer of this project would want changed?

Judge the *code*, not the wording of the tool's message. A finding with an awkward
message that points at a real defect is a real issue; a well-worded message about
correct, intentional code is not.

| Label | Use it when | Examples |
|---|---|---|
| `real issue` | The code has a genuine defect, security weakness, or clear correctness problem at or immediately around the flagged lines, and a maintainer would want it fixed. | An unchecked value reaches `eval`; a variable used before it is defined; a hardcoded credential in source. |
| `not an issue` | The code is correct or deliberate and the finding is a false alarm, a style preference the project does not hold, or a rule applied where it does not fit. | An "unused" parameter required by an interface; a documented `eval` on a constant; test code that intentionally does the flagged thing. |
| `unclear` | After at most about five minutes you cannot decide from the code and reasonable project context. Use it when the answer depends on knowledge you do not have, **not** as a way to avoid deciding. | Behavior depends on a caller you cannot see; the intent is ambiguous. |

Rules of thumb:

- Test files, examples and documentation count as code: judge them by whether the flagged
  construct is a problem *there*. Deliberately bad code in a test that exists to
  exercise a failure is `not an issue`.
- A real but trivial problem (for example, an unused local variable) is still a
  `real issue` if a maintainer would fix it. Do **not** invent a fourth "minor" label;
  severity is analyzed separately and is not part of agreement.
- If two labelers could reasonably differ, that is what calibration is for. Do not
  agonize; pick the label that best fits the definitions and say why in `note`.

## Procedure

**Round 1 — calibration (10 items).** Both labelers label the same 10 items independently
(`labeling/calibration/`). Then, together, compare: for each disagreement, discuss until
you understand *why* you differed, and write down any clarification that should apply to
future items in the "Clarifications" section below (append; do not silently reinterpret).
Calibration labels are **not** used in the reported agreement figure: they are practice,
and the discussion changes how you label afterward.

**Main round.** Each labeler independently labels the sampled items. Sample: **all**
unmatched findings if there are 150 or fewer, otherwise a seeded random sample of 150
(the seed and the sampling script's output are recorded with the round). Findings for the
same case are spread through the order; label in the given order.

**Agreement.** When both have finished, compute Cohen's κ, raw agreement and the confusion
matrix (`python -m evaluation.labeling.agreement`). κ is reported over all three labels,
and again with `unclear` merged into `not an issue`, because `unclear` is an escape hatch
whose meaning differs between people. With about 150 items the interval on κ is wide; the
report says so and does not lean on the customary "substantial agreement" wording.

**Resolution.** Only after agreement is computed, the two labelers meet and settle every
disagreement by discussion. The resolved label goes into the adjudication file with
`resolution: discussion` (or `agreed` where both already matched). Both original labels
stay in their own files, untouched. An item the pair cannot settle becomes `unclear`.

**How the labels are used.** Precision (share of adjudicated findings labeled `real
issue`), false positives per pull request, and any per-rule breakdown are computed from the
resolved labels. `unclear` items are reported separately and the headline precision is
shown both with them excluded and with them counted as `not an issue` — both numbers, never
just the flattering one.

## Files

| File | Written by | Contents |
|---|---|---|
| `calibration/calibration-01.items.json` | script | the 10 items with code context (machine-readable) |
| `calibration/calibration-01.sheet.md` | script | the same items, formatted for reading |
| `labels/calibration-01.labeler-a.csv`, `.labeler-b.csv` | each labeler | `item_id,label,note` — one row per item |
| `label.schema.json` | maintained | the item, label and adjudication record formats |

Label files are plain CSV with exactly the header `item_id,label,note`; `label` is one of
`real issue`, `not an issue`, `unclear`. `python -m evaluation.labeling.agreement
--items … --a … --b …` validates both files (every item exactly once, legal labels, no
extras) before computing anything, and refuses to compute on invalid input.

## What this protocol does not fix

- Two people from one team, labeling third-party code, are a small and possibly correlated
  panel. Agreement measures whether *these* labelers apply these definitions the same way,
  not whether the labels are "true".
- Labelers see only a slice of a project; some `unclear` items are unavoidable.
- The definition of `real issue` is a judgement about maintainers' wishes. Different
  projects would draw the line differently; results describe this rubric.

## Clarifications (append during calibration; date each entry)

*(none yet)*
