# 002 — How to score recall against an oracle that over-redacts

**Date:** 2026-08-06
**Status:** Decided
**Blocks:** `DEFINITIONS.md`, M1 (baselines), M3 (the model)
**Fork source:** Not in the brief. Surfaced by M0 measurement, per the brief's instruction that
unlisted forks be surfaced rather than picked.

---

## The question

The project depends on the CFPB's `XXXX` markers as a free recall oracle. M0 measured what they
actually mark, and a substantial share of markers are not personal information at all:

| pattern | narratives | is it PII? |
|---|---:|---|
| `XXXX points` / `days` / `bureaus` | 16,891 (7.5%) | No — plain counts |
| `$ XXXX` | 5,344 (2.4%) | No — a dollar amount |
| `XXXX %` | 967 (0.4%) | No — an interest rate |
| `XXXX CFR` | 135 (0.1%) | No — a legal citation |

Hand inspection of 100 narratives found a MacBook Pro redacted to `XXXX XXXX XXXX XXXX`, the
number three redacted in "all XXXX bureaus", and the word *may* redacted out of a quoted
regulation: `"a card issuer XXXX not take any action"`.

So a marker is **not** a reliable positive. A model that correctly declines to redact the number
three is scored as having missed. Recall measured against raw markers understates true recall by
an amount that, before this decision, was unknown.

## The options

| | approach | what it produces |
|---|---|---|
| **A** | Score every marker as a positive | An honest lower bound on recall |
| **B** | Hand-label a gold set of narratives | Ground truth on a sample |
| **C** | Drop markers whose context marks them non-PII, score against the rest | A sharpened oracle, using our own rules |
| **D** | Accept the CFPB standard as the definition of correct | Recall against the published standard |

## The decision

**Do all four — and use B as the referee that ranks A, C and D.**

The instruction that produced this decision was "run all four, rank by accuracy". Unlike
[decision 001](001-what-counts-as-re-identification.md), that is directly executable here, with
one structural point worth stating explicitly:

**B is not a fourth competitor. It is the only one of the four that produces ground truth, and
therefore the only thing that makes "rank by accuracy" a meaningful instruction at all.**

A, C and D are three *scoring conventions* — three ways of deciding what the oracle asserts.
Ranking them requires knowing which markers are genuinely PII, and the only way to know that is
for a human to look. So:

1. **B produces the yardstick.** A stratified sample of narratives is hand-labelled at the span
   level: for every marker, was that genuinely personal information? Sampling is seeded and the
   labels are committed.
2. **A, C and D are then scored against B.** Each convention makes a claim about every marker.
   B says whether that claim was right. This yields a measured accuracy per convention, and the
   ranking the instruction asked for.
3. **The winner becomes the primary recall metric.** The other two stay in the results table,
   because the gap between them is itself informative about how much the oracle can be trusted.
4. **A is reported regardless**, as the conservative floor, whether or not it wins. It is the
   number that requires no judgement from us at all, and a reader who distrusts our labelling
   can still use it.

## Consequences and costs

- **This creates a human dependency.** Hand-labelling is the one part of this project that
  cannot be generated, because generating it is precisely what would destroy its value as ground
  truth. Sample size, labelling protocol, and who does it are settled in a follow-up decision
  before M1 starts.
- Any model-assisted pre-labelling — where a model proposes and a human corrects — must be
  disclosed in `docs/03-baselines.md`, including the correction rate, since a human who mostly
  agrees with a machine has produced a weaker label than one who started from blank.
- The over-redaction rate becomes a published number in its own right. It is a finding about the
  CFPB corpus that anyone else using these markers as labels needs, and as far as we can tell it
  is not documented elsewhere.
- C's filter rules are committed and readable, so a reader can see exactly what judgement was
  injected and disagree with it specifically rather than in general.
