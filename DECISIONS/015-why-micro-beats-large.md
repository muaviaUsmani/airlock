# 015 — Micro beats large because it cannot memorise the injector

**Date:** 2026-08-09
**Status:** **SUPERSEDED IN PART, same day.** The measurements below stand. The
*explanation* does not: a later ablation showed the effect is caused by our own
fixed 3-epoch training schedule, not by capacity. See the amendment at the
bottom, and [decision 017](017-the-training-recipe-invalidates-the-size-comparison.md).
**Blocks:** the M3 headline, `docs/04-model.md`, README

---

> **Read the amendment first.** This file was written before the epoch ablation
> ran. Its title is wrong: micro does not beat large because it cannot memorise
> the injector — it beats large because we trained every arm for three epochs
> regardless of when each one had converged. Left in place unedited, because
> deleting a superseded conclusion hides how it was reached.

---

## The claim being defended

M3 reports the 70.7M encoder beating the 434M one by ~5 F1 on the headline set.
That is the opposite of the prediction, so it was attacked before publication.

## The test

`scripts/m6_overfit_gap.py` scores every arm along a transfer curve, using the
control set `docs/04-model.md` pre-registered for exactly this question — the
same narratives rendered with *training* templates versus held-out ones.

4,000 narratives per set, three seeds per arm, F1 %:

| arm | seen templates | stratified | natural_v2 | surrogate (headline) | drop |
|---|---:|---:|---:|---:|---:|
| micro 70.7M | 96.6 ±0.4 | **94.7 ±0.5** | 95.2 ±0.3 | **85.5 ±0.5** | **11.1** |
| base2 184M | **98.2 ±0.1** | 92.0 ±0.6 | 95.1 ±0.2 | 80.0 ±2.9 | 18.1 |
| large 434M | **98.2 ±0.1** | 91.5 ±1.5 | 95.0 ±0.2 | 80.1 ±1.9 | 18.2 |

The surrogate column reproduces `results/m3_arms.csv` exactly, seed for seed,
which is the check that this diagnostic is scoring the same thing the headline
does.

## What it shows

**On the training distribution the larger arms win** — 98.2 against micro's
96.6. Capacity is not useless; it buys in-distribution accuracy exactly as
expected.

**They then give back 18 points reaching real prose, where micro gives back 11.**
That is the overfitting signature: high in-distribution, steeper decline, worse
where it counts.

So the honest statement of the result is *not* "the small model is better". It
is:

> The larger arms have enough capacity to memorise the injector's carrier
> phrasing. Micro does not, and on a task evaluated against real prose that
> inability is an advantage.

The divergence begins as soon as phrasing is held out — micro already leads on
`stratified` (94.7 vs 92.0/91.5) — and roughly triples once the carriers are
gone entirely.

## Three limits on the explanation, which stay attached to it

1. **This is a step, not a capacity curve.** base2 (184M) and large (434M)
   degrade identically, 18.1 versus 18.2. A straightforward "more parameters
   memorise more" account predicts large should be worse than base2, and it is
   not. What the evidence supports is a threshold below 184M, not a monotonic
   relationship. Saying "bigger overfits more" would overstate it.
2. **`natural_v2_hard2` does not discriminate.** All three arms land at
   95.0–95.2. It is naturally distributed and dominated by easy DATE spans, so
   quoting it as a transfer result would say the arms are equivalent. Only the
   surrogate set separates them, and any published transfer claim must name
   which set it came from.
3. **Hypothesis (a) is untested.** Whether 15,000 examples underdetermine 434M
   parameters needs a training-set-size sweep — each arm trained at 2k/5k/15k,
   compared by curve shape — not an evaluation. Roughly nine runs, ~1.5 GPU
   hours. Until that runs, "undertrained" and "overfit" are not separated;
   this file only rules in memorisation, it does not rule out starvation.

## Related correction

HANDOFF §4 also flags base scoring 68.0% recall here against 70.5% previously,
calling it a contradiction of the "better carriers → better model" story. base2's
three seeds are 64.4 / 71.6 / 68.0, spread ±3.6. **70.5 falls inside that range.**
The apparent reversal is most likely one seed being compared against a mean, not
a real effect. Worth confirming what the 70.5 figure was before treating it as
evidence of anything.

---

## AMENDMENT, 2026-08-09 (same day)

Everything above is a correct description of *what* the arms do. The causal
claim — that capacity buys memorisation — was tested further and does not
survive.

`scripts/m6_epoch_ablation.sh` retrained every arm for **one** epoch, changing
nothing else, and re-scored on the same headline set:

| arm | 1 epoch | 3 epochs | delta |
|---|---:|---:|---:|
| micro | 83.8 | **85.5** | −1.8 |
| base2 | 82.1 | 77.4 | +4.7 |
| large | **84.7** | 78.0 | +6.7 |

**The ranking inverts.** At three epochs micro leads by 7.5; at one epoch large
leads by 0.9. The larger arms are not intrinsically worse at this task — they
were trained past their own optimum by a schedule that was never chosen per arm.

The training losses said so before the ablation did: after a single epoch large
is already at 0.0444 and by epoch two at 0.0006, while micro is still at 0.2821
after one epoch and 0.0053 after three. Micro is the only arm that *wants* the
third epoch.

So the transfer curve in the table above is real, but it is a curve produced by
**over-training the high-capacity arms**, not by capacity itself. Both readings
predict "large memorises the injector"; only this one identifies why.

### What this changes

- The M3 headline cannot be stated as a result about model size. The defensible
  version is: *under a single recipe applied unchanged across three scales, the
  larger models overfit and lose.*
- The claim in this file's original body — "the larger arms have enough capacity
  to memorise the injector's carrier phrasing, micro does not" — should be read
  as "…given three epochs", which makes it a statement about our schedule.
- The limit noted above (base2 and large degrading *identically*, which a pure
  capacity story cannot explain) now has an explanation: both had converged well
  before the schedule ended, so both were over-trained by a similar margin.

### What is still not established

- **That large actually wins.** The 1-epoch gap is 0.9 F1 on a single seed,
  inside large's ±1.9 seed spread. Three seeds would be needed to claim it.
- **That one epoch is right.** It is a second arbitrary point, not a principled
  stopping rule. The fix is a validation split with per-arm early stopping, and
  a learning rate that is not hardcoded at 3e-5 for every scale.
- **Hypothesis (a), data starvation**, is separately refuted by
  `results/m6_data_scaling.txt` — the larger arms get *worse* from 2k to 15k
  rows, which is what over-training predicts and what starvation forbids.
