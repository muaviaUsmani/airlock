# 007 — Tier 3 frequencies cannot come from the markers

**Date:** 2026-08-06
**Status:** Decided. Amends [decision 004](004-two-injection-distributions.md).
**Blocks:** M4 (the attack), M5 (utility)
**Fork source:** Not in the brief. Surfaced by the first M4 dry run.
**Resolved under:** the standing instruction in
[the constitution](../.specify/memory/constitution.md), principle I — build every branch,
publish the comparison

---

## What the first attack run revealed

Running the M4 attack on `natural` gave a raw-text unique re-identification rate of **8.6%**.
That looked far too low against the M2 finding that amount + date is 96.0% unique in the
database, so the cause was measured rather than explained away:

```
narratives with an INJECTED amount:   9.4%
narratives with an INJECTED date:    97.5%
narratives with BOTH:                 9.0%   <-- ceiling for an amount+date attack
raw text achieved:                    8.6%
```

**The attacker is near-optimal. The data is wrong.** It is extracting almost everything present;
almost nothing is present to extract.

## The structural error

`natural` was derived from the CFPB `XXXX` marker categories. Markers record **only what the
CFPB redacted**.

Tier 3 quasi-identifiers are, by definition, the things the CFPB **does not** redact. That is the
entire reason tier 3 exists in `DEFINITIONS.md` — it is information that passes every PII
standard and still identifies a customer. M0 measured exactly this:

> *"Amounts are NOT redacted by the CFPB — they are reformatted and kept."*
> Intact dollar amount present in **44.2%** of narratives.

So `AMOUNT` appears at 2.5% of resolved marker spans not because complaints rarely mention money,
but **because money is rarely redacted**. The marker oracle cannot see it. Deriving tier 3
frequencies from markers asks the oracle a question it is structurally incapable of answering,
and the answer it gives is close to zero by construction.

This is the same failure as the `DATE`-shape bias in decision 004, with the sign reversed and
worse consequences. That one over-weighted a category that labels itself. This one
**under-weights precisely the categories that make re-identification possible**, and it lands
directly on the headline.

## The decision

**Tier 3 injection frequencies are measured directly from surviving text, not from markers.
Both distributions are built and both are published.**

| set | tier 1 & 2 | tier 3 | role |
|---|---|---|---|
| `natural` | marker-derived | marker-derived | kept, as the under-estimate, and labelled one |
| `natural_v2` | marker-derived | **measured from surviving text** | **the headline** |

Tier 3 rates come from counting what actually survives in real published narratives — intact
`{$x.xx}` amounts, `XX/XX/XXXX` date markers, merchant mentions, weekday and time-of-day
references. That measurement is committed in `scripts/m2_tier3_survival.py` and needs no oracle
at all: the values are still in the text, so they can simply be counted.

Both are run through the full attack, and the gap between them is itself the finding — it is the
size of the error that using a redaction oracle to estimate non-redacted content produces.

## Why `natural` is kept rather than deleted

Because the comparison is the point. `natural` is what a careful team would build by following
the brief's instruction literally, and it produces a headline roughly five times too small. That
is worth showing rather than quietly correcting, and it is the most transferable lesson in the
project: **an oracle built from redaction decisions cannot tell you about the things nobody
redacted.**

Every table names its set. `natural` is labelled an under-estimate wherever it appears.

## What does not change

- **The training set is unaffected.** Training uses `stratified`, which is uniform across
  categories by construction, so the encoder currently training is not invalidated.
- **Decision 004's binding rules still hold** — per-category scoring from `stratified`, headline
  from a natural set. Only which natural set supplies the headline changes.
- **The direction of the remaining error is still stated.** `natural_v2` fixes tier 3 but tier 1
  and 2 remain marker-derived and therefore still carry the resolvability bias from decision 004.

## A second defect the same run exposed

The attacker returned nothing unless it could extract a dollar amount, which made `regex` score
**0.0%** — a perfect redactor, apparently. It is not. The regex baseline strips `$x.xx` patterns,
so it destroys the attacker's only entry point rather than protecting the customer.

An attacker that gives up without an amount is measuring one field, not the leak. So the matcher
is generalised to work from any available combination — date plus merchant, merchant plus city,
name alone — with amount as one field among several rather than a precondition. Decision 005's
pre-registered selection rule is unchanged and still governs which configuration is quoted.
