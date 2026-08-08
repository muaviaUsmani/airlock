# Limitations

Written as they are discovered, not assembled at the end. Everything here is a thing this
project does **not** do, or does with a caveat a reader needs before quoting a number.

---

## The premise changed partway through

The brief specified that *everything* run on an M1 MacBook with no GPU, and listed it under
"already decided, do not revisit". **It was revisited**, deliberately, by the human, on
2026-08-08 — see [decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md).

| | where it runs |
|---|---|
| model training, ablations, seed sweeps | rented RTX 3090 (~$0.14/hr) |
| **inference latency and peak memory** | **M1 MacBook, 16GB, no GPU** |
| Presidio, spaCy, regex baselines | M1 (CPU-bound, deterministic) |
| the M4 attack | M1 |

**Why this does not weaken the privacy argument.** The premise is that the *data* cannot leave
the building, which constrains inference. The training data here is public CFPB text with
synthetic personal information we generated ourselves, so there is nothing confidential in it —
a consequence of [decision 003](../DECISIONS/003-no-hand-labelling.md), where ground truth
became generated rather than annotated.

**What it does change:** the claim is *"runs on a laptop"*, not *"trainable on a laptop"*. A
reader who needs the second should know that a full training run took **6.8 hours on the M1** and
made the machine unusable for anything else, against **~12 minutes** on a rented 3090.

## Reproducing without a GPU

`make repro` must work from a clean checkout. The training step names its hardware and expected
runtime, and trained weights are published so that evaluation, the attack, and the utility
numbers regenerate without retraining. **A repro that silently requires a rented A100 is not a
repro.**

## Numbers produced on different hardware are not mixed

Hardware and numeric precision differ between the M1 and the rented GPU, so a comparison is
regenerated on one platform rather than stitched across two. Where an older M1-trained number is
kept, it says so.

## Everything else

Filled in as the remaining milestones produce it. Known items already recorded elsewhere and due
to land here:

- injected text is more uniform than organic prose, so scores on it flatter every method
  (`scripts/m2_inject.py`)
- recall against `XXXX` markers is a lower bound with an unmeasured gap
  ([decision 003](../DECISIONS/003-no-hand-labelling.md))
- the category estimator is unreliable outside `DATE`, which bounds what the surrogate transfer
  test can cover ([decision 010](../DECISIONS/010-hardening-the-injector.md))
- entity-site carriers are chosen by spaCy, which inflates the spaCy baseline — the conservative
  direction for this project's claim, and reported wherever those categories appear
- re-identification rates are conditioned on a 10,000-customer database; uniqueness falls as
  population grows ([docs/05-attack.md](05-attack.md))
