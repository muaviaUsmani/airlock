# 010 — Hardening the injector

**Date:** 2026-08-08
**Status:** Decided
**Blocks:** M3 (retraining), M4
**Follows from:** [decision 008](008-the-transfer-metric-was-invalid.md) and the estimator
validation in `results/m2_estimator_accuracy.txt`

---

## What broke

M3 produced an encoder scoring 90.1% on injected text and 59.7% on real prose, failing outright
on `ORG_THIRD_PARTY` (0.8%) and `TEMPORAL` (7.9%). Diagnosis: it learned **carrier contexts**, not
entity types.

The obvious fix — mine real carrier sentences from the corpus instead of writing them — was built
and then stopped, because validating the component it depends on showed the category estimator
gets **23.8% correct, 14.7% actively wrong**, and is reliable only for `DATE`. Carriers mined
under those labels would be mislabelled, and the transfer test that grades the model uses the
same estimator, so training data and grader would share the mistake.

Four changes, in descending order of how much they matter.

---

## 1. Mine only where context *determines* the type, not where it hints at it

The distinction the estimator was missing. Some surviving context leaves no room for
interpretation:

| context | what the marker must have been |
|---|---|
| `ending in XXXX` | an account identifier |
| `case number XXXX` | a case reference |
| `$ XXXX` | an amount |
| `XX/XX/XXXX` | a date |
| `social security number XXXX` | a government ID |

Other context merely suggests: `with XXXX` could be a person, a bank, or a city. The old rule set
mixed both kinds and reported one accuracy figure across them.

**Only determining contexts are mined.** Coverage drops sharply and is published as a number.
This is a precision-for-recall trade made deliberately, because a mislabelled carrier is worse
than a missing one — it teaches the model something false and the grader agrees with it.

**Consequence, stated plainly:** determining contexts exist mostly for tier 1 and for
`AMOUNT`/`DATE`. For tier 2 — the categories this project exists to catch — there is usually no
phrase that names the type. `my ex-husband XXXX` tells you the marker is a *name*, not a
relationship. **So mining cannot fix the categories that failed**, and change 2 exists for them.

## 2. Real syntactic sites for the categories mining cannot reach

For `PERSON`, `ORG_THIRD_PARTY` and `LOCATION_FINE`, take **clean narratives** — real complaints,
never redacted — run entity recognition over them, and substitute our synthetic value at a
position where a real entity of that type already stood.

The prose is real, the syntactic position is real, and the label is exact because we chose what
went in. No category estimation is involved anywhere.

**The bias this introduces, and its direction.** Insertion sites are chosen by spaCy, so spaCy is
being tested partly on positions it selected. That inflates the spaCy baseline. It is the
*conservative* direction for this project's claim — it makes the baseline harder to beat, not
easier — and it is reported wherever those categories appear.

## 3. Diversify the values, because ten strings can be memorised

`ORG_THIRD_PARTY` drew from **ten** bank names; `PROTECTED_ATTR` from six phrases; `HEALTH` from
eight. A model can memorise ten strings and appear to understand a category.

Pools are expanded by roughly an order of magnitude, and — more importantly — **the evaluation
pool is disjoint from the training pool**. A model that memorised training values scores zero on
held-out ones, which turns a hidden failure into a measured one.

This is the value-level equivalent of the template split, and its absence is why the earlier
template split looked reassuring while the model was memorising something else entirely.

## 4. Hard negatives — the model has never seen what to leave alone

`DEFINITIONS.md` section 1 lists what is explicitly **not** personal information: plain counts
("all three bureaus", "700 points"), interest rates, credit scores, regulation citations
("12 CFR 1026"), product models ("MacBook Pro"), and the company the complaint is filed against.

The model has never seen a single one as a negative. Everything resembling an entity in training
was a positive, so "flag anything that looks like a name or a number" was a winning strategy on
our data and a losing one on real text. Its 94.6% precision on real prose alongside 59.7% recall
is consistent with a model that fires rarely but has no notion of a deliberate non-target.

Hard negatives are injected at measured corpus frequencies and **never labelled**, so flagging
one costs precision.

---

## What this changes about the transfer test

The surrogate transfer test uses the same estimator, so it inherits the same unreliability. It is
restricted to categories where the estimator is **determining rather than suggestive**, and the
report names which categories are covered and which are not.

For categories that cannot be covered — most of tier 2 — the honest statement is that **this
project has no valid real-prose test for them**, and that goes in `docs/08-limitations.md` rather
than being papered over with a number.

## What is deliberately not done

- **No change to the architecture.** The evidence points at the data. Changing both at once would
  make the result uninterpretable.
- **No change to `DEFINITIONS.md`.** The categories stay as locked at M0.
- **No tuning against the transfer number.** Hyper-parameters stay where they were, so any change
  is attributable to the data.

## How the result will be read

Against the M1-trained encoder, which is the control. If tier 2 recall on real prose moves
sharply, decision 008's diagnosis was right and the injector was the problem. If it does not, the
diagnosis was wrong and the limitation is deeper than training data — which is a publishable
finding and a more interesting one.

Per [decision 011](011-training-moves-to-rented-gpu.md), this now runs with **three seeds**, so
the comparison carries a variance estimate rather than resting on n=1.
