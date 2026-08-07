# 005 — How the adversary matches: publish the curve, not two points

**Date:** 2026-08-06
**Status:** Decided
**Blocks:** M4 (the attack)
**Fork source:** Section 6 of the project brief, open fork #3
**Resolved under:** the standing instruction in
[the constitution](../.specify/memory/constitution.md), principle I — build every branch,
publish the comparison

---

## The question

The brief states it:

> *Exact joins on extracted values only, or fuzzy matching on approximate details (dates near
> each other, amounts within a range). Exact is honest and weak; fuzzy is realistic and much
> harder to bound. Not decided.*

## The decision

**Build both, and publish them as one curve rather than two points, because they are not two
methods.**

The framing worth stating explicitly:

> **Exact matching is fuzzy matching with zero tolerance.**

An attacker that extracts an amount, a date and a merchant from redacted text, then queries the
database, is described entirely by two things: **which fields it uses**, and **how much slack it
allows on each**. Set the slack to zero and you have the exact join. Loosen it and you have the
fuzzy matcher. They sit on one continuum.

That matters because reporting "exact gets A%, fuzzy gets B%" invites the obvious question — *B%
at what tolerance?* — and has no answer. A tolerance sweep answers it, costs barely more to run,
and is what the standing instruction asks for when branches form a parameterised family.

So the adversary is one function of two arguments:

| axis | values swept |
|---|---|
| **fields** | amount · amount+date · amount+date+merchant · +name · +city |
| **tolerance τ** | exact · ±1 day · ±3 days · ±7 days, and ±$0 · ±$1 · ±$5 · ±5% |

Every cell yields U, K and R (per [decision 001](001-what-counts-as-re-identification.md)) and
an attacker false-positive rate, for each of raw, Presidio-redacted and Airlock-redacted text.

## Why this fork is more tractable than it looks

Unlike [decision 001](001-what-counts-as-re-identification.md), where three definitions of
"re-identified" could not be ranked because there is no ground truth about what the word ought
to mean, **this fork has ground truth.** Every injected narrative records the `customer_id` it
was built from. So for any matcher configuration we can measure directly:

- **true re-identification rate** — the correct customer was found
- **false-positive rate** — a confident match on the wrong customer

That second number is what bounds the fuzzy matcher, and it is the answer to the brief's worry
that fuzzy is "much harder to bound". It is only unbounded if you decline to measure how often
it is wrong. `DEFINITIONS.md` already requires that: *"an attacker who guesses constantly is not
a good attacker."*

## The safeguard, which matters more than the sweep

A tolerance sweep creates an obvious way to manufacture a flattering headline: loosen τ until
Presidio-redacted text leaks a lot, tighten it until Airlock-redacted text leaks little, and
report the gap. That would be fraud dressed as a parameter choice.

**So the selection rule is pre-registered here, before the attack code is written:**

1. **τ and the field set are chosen on RAW text only** — the unredacted condition, where no
   redaction method is involved and therefore none can be favoured. The chosen configuration is
   the one maximising the attacker's true re-identification rate subject to its false-positive
   rate staying below 5%.
2. **That single configuration is then applied unchanged to every redaction method.** No
   per-method tuning, ever.
3. **The full sweep is published anyway**, so a reader can see the headline's position on the
   surface rather than taking the selection rule on trust.
4. If the headline's ranking of redaction methods **changes across the sweep**, that is a finding
   about instability and goes in the README, not a reason to search for a configuration where
   it does not.

Point 1 is the load-bearing one. Tuning the attacker on raw text means the attacker is optimised
against nobody's redaction, so the comparison it then performs is not rigged for or against any
method.

## What gets reported

- **Headline:** U, at the pre-registered configuration, for raw / Presidio / Airlock.
- **Beneath it:** K and R at the same configuration.
- **The surface:** re-identification rate against τ, one line per redaction method, with the
  pre-registered point marked.
- **The attacker's own error rate** at every point, because a re-identification rate quoted
  without its false-positive rate is meaningless.
- **Stability**, per decision 001 — how far U moves across the sweep, which this design produces
  as a by-product rather than needing a separate experiment.

## Consequences

- The M4 harness is parameterised on `(fields, τ)` from the start. Decision 001 already required
  this for stability measurement, so the two decisions agree.
- Extraction and matching are separate stages. What the attacker can *extract* from redacted
  prose is a property of the redaction; how it *matches* is a property of the attacker. Keeping
  them apart is what allows one attacker to be run against all three redaction methods.
- The sweep is roughly 20 configurations × 3 methods. Cheap — the database is 359,375 rows and
  the join is indexed.
