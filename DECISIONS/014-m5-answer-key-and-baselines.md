# 014 — M5 grades against a partly missing answer key, and now reports baselines

**Date:** 2026-08-09
**Status:** Decided by the human. Bug fix applied regardless; the reporting
change was the fork.
**Blocks:** M5, the leakage-vs-utility trade table

---

## What the handoff said, and why it was not acted on

The handoff instructed:

> *Note `relief` scored 0% even on raw text in the smoke test — likely a bad
> question. Check, and drop it with a reason if so.*

**Checked. It did not score 0%.** The committed smoke output
(`results/m5_utility.csv`, n=12) records `relief` at **75.0%, the highest of the
three questions**. Nothing in the repository supports the 0% figure. The
condition attached to the instruction was not met, so the question was not
dropped.

This is recorded rather than quietly corrected because a handoff is exactly the
kind of document a later reader trusts without re-deriving.

## The bug that was actually there

`sub_product` was the failing question, and part of the failure was mechanical.

**8.4% of the corpus — 11.2% of the graded slice — has no CFPB `Sub-product`.**
`str(nan)` is the string `"nan"`, and the option list was built with
`sorted({str(t["sub_product"]) for t in truth})`. So two things happened at once:

1. For those rows the answer key was the literal string `"nan"`, which no reader
   can produce. They were scored as misses.
2. `"nan"` was offered to the reader **as a valid choice on every row**, acting
   as a distractor throughout.

A diagnostic probe on 20 raw narratives caught the model answering sensibly
against a `nan` key six times.

This is the same failure the script's own comment already documents one column
over — *"showed up as a suspiciously low raw-text score rather than as an
error"*. It happened again, and it presented the same way.

**Fix, applied as a plain bug fix:** a row with no answer key is not a question
the reader got wrong, it is not a question. Missing truths are excluded from
that question's denominator, and `"nan"` no longer appears among the options.

## The fork: what to do about weak questions

Even with the bug fixed, two of the three questions are close to worthless as
measurements, and for a reason no fix addresses — their **majority-class
baselines are high**, so accuracy mostly reports the base rate:

| question | distinct labels | majority baseline | observed on raw text |
|---|---:|---:|---:|
| `sub_product` | 2 | 85.7% | 35.7% (excluding null-key rows) |
| `issue` | 46 | 24.1% | 45–58% |
| `relief` | 2 (derived from 6) | 82.2% | 60–75% |

`issue` is the only question that beats its baseline. `relief` sits *below*
always-answering "no" — consistent with the mechanism the handoff guessed at
even though its evidence was wrong: *Company response to consumer* is recorded
after the complaint is filed, so the consumer's narrative cannot contain it, and
the reader correctly answers UNKNOWN.

**Options considered:** keep all three and report baselines; keep all three but
headline only on `issue`; drop `relief`; drop both `relief` and `sub_product`.

**Chosen: keep all three, publish each against its majority-class baseline.**
Nothing is discarded, and a reader can see for themselves which question carries
signal. This follows constitution principle IV — a question that turns out not
to measure anything is a finding, and it belongs in the table rather than in a
deleted line of code.

## A caveat that this does not fix

All of the above is measured on **raw, unredacted text**. It is a noise floor,
not redaction damage. M5 reports utility lost as raw − redacted, so a constant
floor largely cancels — but it compresses the dynamic range, and the absolute
utility figures in the trade table read lower than the redaction warrants. That
should be stated wherever the trade table is published.

## Also changed

The `airlock` condition is now **one condition per encoder arm** rather than a
single `--model-dir`, per the standing instruction to build every branch and
publish the comparison. `micro` and `base2` are run as `airlock:micro` and
`airlock:base2`.

One caveat travels with that: M4's re-identification figure was measured for one
arm, so both airlock rows in the trade table currently share it. That column is
not per-arm and should not be read as if it were.

---

## ADDENDUM, 2026-08-09 — a third unreachable answer key, in the same script

Running M5 at full size exposed one more instance of the same failure, on the
one question that had appeared healthy.

`options["issue"]` was built as `sorted({...})[:12]` — the first twelve labels
**alphabetically** out of 27 present in the graded slice. Only **32.6% of the
true answers were among the options offered**. The two most frequent correct
answers, "Problem with a purchase shown on your statement" and "Other features,
terms, or problems", were excluded for beginning with "P" and "O".

So `issue` was capped at 32.6% before the reader saw any text, and scored 12.9%
against a 12.0% majority baseline — which read as "redaction destroys the
ability to answer this", when in fact the question was mostly unanswerable by
construction. It is also why an early 20-row probe suggested `issue` was the
one question carrying signal: at that size the handful of labels present all
happened to fall inside the alphabetical cut.

**Fixed.** Every label present in the graded slice is now offered, with no cap,
and the script checks the invariant explicitly:

> a correct answer must always be among the options offered

printing the achievable ceiling whenever it is not. Both this bug and the `nan`
bug violated that same invariant, and both produced a plausible low score rather
than an error — which is why it is now asserted at runtime instead of assumed.

The trade table was regenerated after the fix. The earlier numbers penalised all
methods equally, so the *ranking* was unaffected; the absolute utility figures
were not trustworthy.
