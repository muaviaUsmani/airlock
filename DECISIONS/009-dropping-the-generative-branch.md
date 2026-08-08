# 009 — Dropping the generative branch

**Date:** 2026-08-08
**Status:** Decided. Closes branch B of [decision 006](006-model-architecture.md).
**Blocks:** nothing. Removes ~20 hours of planned work.
**Decided by:** the human, explicitly overriding the standing "build every branch" rule for this
fork.

---

## The decision

**The generative branch is not built.** M3 ships as a single-architecture result: a small encoder,
measured honestly, against the baselines.

The standing instruction in [the constitution](../.specify/memory/constitution.md) is to build
every branch of a fork and publish the comparison. That instruction carries an explicit exception
— it applies *"unless overridden for a specific one"* — and this is that override.

## The reasoning

### 1. It contradicts the project's own premise

The thesis is *a small open-weight model, trained for one narrow job, running alongside a
frontier model* — and specifically one a small team can train and run on their own hardware. The
brief fixes that hardware: an M1 MacBook, 16GB, no GPU.

Measured cost on that machine:

| | encoder | generative (estimated) |
|---|---|---|
| training | 6.8 hours | 5–10 hours |
| inference, 4,000 narratives | ~13 min | 4–6 hours |
| inference per narrative | ~190ms | ~4–5 s |

The inference figure is the disqualifying one. A bank with hundreds of thousands of complaints
running at 4–5 seconds each is looking at **weeks of wall-clock time** on the hardware this
project specifies. That is not a marginal disadvantage to be traded against accuracy; it puts the
method outside the premise regardless of how accurate it turns out to be.

An architecture that only works on hardware the project has ruled out is not a fork worth
resolving. It is a different project.

### 2. Too many unknowns to be worth the spend

The generative branch carries risks the encoder does not: text drift, unreliable character
offsets, output-format sensitivity, and tuning choices (LoRA rank, prompt design, decoding
parameters) each of which could dominate the result. Every one of those needs its own
investigation to interpret the outcome.

Spending ~20 hours to produce a number that might be explained by any of four confounds is a poor
trade when there is **no identified upside specific to this hardware**. The hypothesised
advantage — that LoRA touches fewer weights and so preserves pretrained knowledge better — is
plausible, untested, and would remain confounded even if the number came out well.

### 3. The interesting question was never "which architecture"

[Decision 008](008-the-transfer-metric-was-invalid.md) established that the encoder failed because
it learned **carrier contexts from formulaic training data**, not because of anything about
encoders. That diagnosis points at the *data*, and it is testable with one architecture.

Running a second architecture on the same flawed data would most likely reproduce the same
failure at ten times the cost, and would teach less than fixing the data and measuring the
difference.

## What is published instead

The comparison is not silently dropped. `docs/04-model.md` carries the generative option with:

- the measured encoder costs, and the estimated generative costs above, with their basis
- the three output formats considered and why each was accepted or rejected
  ([decision 006](006-model-architecture.md))
- the specific reason it was not run — hardware premise, not lack of merit
- what would change the answer: a GPU, or a deployment where seconds-per-document is acceptable

**This is an argument from the project's constraints, not evidence that generative redaction is
worse.** On different hardware it may well win, and nothing here should be read as showing
otherwise. The honest claim is narrow: *on the hardware this project specifies, it is not viable,
and we did not test it.*

## What the freed budget buys

One properly constructed encoder run instead of three rushed ones. The specifics are in
[decision 010](010-hardening-the-injector.md).
