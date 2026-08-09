# 017 — The training recipe invalidates the model-size comparison

**Date:** 2026-08-09
**Status:** Measured. Supersedes the causal claim in
[decision 015](015-why-micro-beats-large.md).
**Blocks:** the M3 headline, README, `docs/04-model.md`, any future size comparison

---

## The result

M3 published a 70.7M encoder beating a 434M one by ~5 F1 and treated it as a
finding about model size. It is not. Retraining every arm for **one** epoch,
changing nothing else, inverts the ranking:

| arm | 1 epoch | 3 epochs | delta |
|---|---:|---:|---:|
| micro 70.7M | 83.8 | **85.5** | −1.8 |
| base2 184M | 82.1 | 77.4 | +4.7 |
| large 434M | **84.7** | 78.0 | +6.7 |

At three epochs micro leads by 7.5 points. At one epoch large leads by 0.9.

## Why it happens

`scripts/m3_train_encoder.py` applies one recipe to every arm:

- **`LR = 3e-5` for all three scales.** Not a CLI argument — a module constant.
  Reasonable for xsmall and base; `deberta-v3-large` is well known to want ~1e-5
  and to be unstable above it.
- **`EPOCHS = 3`, fixed**, with **no validation split, no early stopping and no
  best-checkpoint selection.** Whatever the last epoch produced is what is saved.
- **Batch varies 16/8/4 purely to fit memory** while the learning rate does not,
  so `large` takes ~3,749 optimiser steps per epoch against micro's ~937 — 4×
  the updates, at a rate already too high for it.

The training losses at 15k rows show the consequence directly:

| arm | epoch 1 | epoch 2 | epoch 3 |
|---|---:|---:|---:|
| micro | 0.3684 | 0.0095 | **0.0053** |
| base2 | 0.1240 | 0.0012 | **0.0005** |
| large | 0.0711 | 0.0006 | **0.0003** |

`large` has fitted the training set by epoch 2 and trains a third epoch anyway.
`micro` is the only arm still learning when the schedule ends — it is the only
one for which three epochs is close to right.

**So the arms were never compared at equivalent points.** Each was scored
wherever a fixed schedule happened to leave it, and the more capacity a model
has, the further past its own optimum that is. The comparison measured our
stopping rule.

## The corroborating result

`results/m6_data_scaling.txt` shows the same cause from another angle. With
epochs fixed, more data means more steps means deeper over-training:

| arm | n=2,000 | n=5,000 | n=14,995 |
|---|---:|---:|---:|
| micro | 77.0 | 83.9 | **85.5** |
| base2 | **86.3** | 85.1 | 77.4 |
| large | **85.4** | 83.4 | 78.0 |

Both larger arms **peak at the smallest data budget tested and decline**, while
micro improves. That also disposes of HANDOFF §4's hypothesis (a): 15,000
examples do not starve the larger arms — starvation predicts improvement with
more data, and the opposite happens.

(`head(n)` was checked as an unbiased subsample before this was believed:
spans/row 3.82 and mean length ~1067 are identical across the 2k, 5k and full
slices, and category shares sit at ~6.3% throughout.)

## What may and may not be said now

**May be said:** under a single training recipe applied unchanged across three
scales, the larger models overfit and lose. The recipe, not capacity, produces
the ordering.

**May not be said:** that smaller models are better at PII redaction; that
capacity does not help; that large "wins" — the 1-epoch gap is 0.9 F1 on one
seed, inside large's ±1.9 seed spread.

**One epoch is not the fix.** It is a second arbitrary stopping point that
happens to favour a different arm. Any future size comparison needs, before it
means anything:

1. a validation split held out of `injected_train_hard2`,
2. per-arm early stopping or best-checkpoint selection on it,
3. a learning rate chosen per scale — and promoted from module constant to
   argument so it can be swept at all,
4. three seeds at whatever configuration results.

Estimated cost: a small LR sweep plus reruns, roughly 3–4 GPU-hours (~$0.70).

## Why this is recorded rather than quietly fixed

The inverted ranking was the most striking result in the project and was one
step from being published as a finding about model size. It survived a transfer
diagnostic ([decision 015](015-why-micro-beats-large.md)) that *confirmed* it
for the wrong reason — the memorisation was real, but attributing it to capacity
rather than to our schedule would have made every follow-on conclusion wrong
while looking well-evidenced.

The lesson generalises past this project: **a comparison across model scales is
only a comparison if each scale is given its own stopping point.** A shared
schedule silently converts a capacity experiment into a schedule experiment, and
the result still looks clean.
