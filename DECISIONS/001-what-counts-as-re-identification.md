# 001 — What counts as "re-identified"

**Date:** 2026-08-06
**Status:** Decided
**Blocks:** `DEFINITIONS.md`, M4 (the attack)
**Fork source:** Section 6 of the project brief, open fork #2

---

## The question

The headline claim of this project is that redaction "reduces the rate at which a customer can
be re-identified from **A%** to **B%**". Both numbers depend entirely on what "re-identified"
is taken to mean, and there are three defensible answers that give three different headlines.

## The options

Given a redacted narrative and a database of synthetic customers, the attacker produces a set of
candidate customers. A narrative counts as re-identified when:

| | definition | what it captures |
|---|---|---|
| **U** | **Unique match** — the candidate set contains exactly one customer, and it is the correct one | "I found them." Intuitive, hard to game. |
| **K** | **Small set** — the correct customer is in a candidate set of size < 5 | Disclosure-control reasoning (k-anonymity). More stable. |
| **R** | **Rank-1** — every customer is scored, and the correct one ranks first | Standard framing in the re-identification literature. Always produces a number. |

## The decision

**Compute all three. Report all three. Publish the comparison rather than a single number.**

The three are nested — a unique correct match is also a top-5 hit and also a rank-1 hit — so
U ≤ K ≤ R by construction. That means they are not really three rival metrics; they are three
points on one curve of "how much narrowing counts as identification". Reporting them together
costs one extra pass over the attack results and makes the result much harder to accuse of
cherry-picking.

The README's headline sentence quotes **U (unique match)**, because it is the most conservative
of the three — it produces the smallest A% and is therefore the claim least vulnerable to
"you have overstated the risk". K and R appear immediately beneath it in the results table.

## A correction to the framing

The instruction that produced this decision was "compute all three and rank by accuracy". That
instruction is right in spirit and needs one adjustment to be executable:

**These three cannot be ranked by accuracy, because there is no ground truth about what
re-identification "really" means.** They are three *definitions* of a phenomenon, not three
*predictors* of a fact. There is no experiment that reveals U to be more correct than K.

Two properties of them *can* be measured, and those are what the comparison table ranks:

1. **Discriminative power** — how sharply the definition separates the redaction methods from
   each other. A definition where raw text, Presidio and Airlock all score within a couple of
   points is telling us very little, whatever its absolute value.
2. **Stability** — how much the number moves when the adversary's matching thresholds are
   perturbed. A definition that swings twenty points when a tolerance changes is measuring the
   attacker's tuning rather than the leak.

Both are computable from the M4 attack output with no extra ground truth. They are reported
alongside the three rates, and `docs/05-attack.md` states plainly that the ranking is on those
two axes and not on correctness.

## Consequences

- M4 emits, per redaction method, the full candidate set per narrative — not just a boolean.
  All three rates are then derived from one attack run.
- The stability measurement requires the attack to run at several matching thresholds, so the
  M4 harness is parameterised on threshold from the start rather than retrofitted.
- `DEFINITIONS.md` defines all three and names U as the headline.
