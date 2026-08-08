# 011 — Training moves to rented GPU; inference stays on the laptop

**Date:** 2026-08-08
**Status:** Decided by the human. Revisits an item the brief marked "already decided, do not
revisit".
**Blocks:** M3 (retraining), M6 (ablations, `make repro`)

---

## What the brief said

> *Everything runs on an M1 MacBook with 16GB of memory. No GPU.*

Listed under **"Already decided, do not revisit."** Revisiting it is the human's call, and this
file records that it was made deliberately rather than drifted into.

## The distinction that makes this possible

**Training location and deployment location are different claims, and only one of them carries
the thesis.**

The premise is *the data cannot leave the building*. That constrains **inference** — the bank
runs the model locally, on real complaints, because sending them out is the thing that was
forbidden in the first place. It says nothing about where the weights were fitted.

And in this project specifically there is no privacy tension at all: **the training data is
public CFPB text with synthetic personal information we generated ourselves.** There is nothing
confidential in it. That is a consequence of
[decision 003](003-no-hand-labelling.md) — because ground truth is generated rather than
annotated, the training set is fully shareable by construction.

So the claim changes from *"trainable on a laptop"* to *"runs on a laptop"*, and only the second
was ever the argument.

## The reasoning

### 1. The laptop cannot do two things at once

Not a comfort complaint — a correctness one. MPS does not multiplex across processes. Running
the evaluation while training was running dropped it to **0.1% CPU** and starved both. Everything
had to be serialised, which is why transfer results took ~49 minutes to surface and why a stuck
watcher went unnoticed for twelve hours.

Serialised work also means the machine is unusable for anything else for the duration, which on a
6.8-hour run is a working day.

### 2. Failed runs are expensive in the only currency that is scarce

Roughly **8 hours of laptop time in this project has produced nothing**: a run stopped when the
category estimator turned out unreliable, and a launch that died silently and was reported as
running. On rented hardware both are about $1 and 25 minutes.

That asymmetry changes behaviour badly. When a run costs a working day, there is pressure to let
a doubtful one finish rather than kill it — which is exactly the pressure that produces results
nobody should trust.

### 3. Every number in this project is n=1

No variance estimates anywhere, because a second seed costs 6.8 hours. This is the weakest
methodological point in the repository and it is purely an artefact of compute. Three seeds on
rented hardware is under an hour and about a dollar.

## The measured basis

| | M1 MPS | A100 40GB (bf16) |
|---|---:|---:|
| throughput | 1.7 seq/s | ~50–70 seq/s |
| one encoder run (15,000 × 3 epochs) | **6.8 hrs** | **~12–15 min** |

| item | cost |
|---|---:|
| one training run, including setup overhead | ~$0.40–0.75 |
| full M6 ablation sweep (~10 runs) | ~$4–7 |
| three seeds of the headline run | ~$2 |

Marketplace prices move; these are estimates and are labelled as such wherever they appear.

## What moves, and what does not

| | where it runs | why |
|---|---|---|
| model training | **rented GPU** | no confidential data, and the laptop is the bottleneck |
| ablations, seed sweeps | **rented GPU** | only affordable there |
| **inference latency and memory** | **M1 laptop** | this IS the claim, so it is measured on the hardware being claimed |
| Presidio, spaCy, regex baselines | either | CPU-bound and deterministic given the seed |
| the M4 attack | laptop | pandas and numpy, no GPU involvement |

**Inference measurement staying on the M1 is not a formality.** "A 300MB model that runs on a
laptop" is the deliverable, so seconds-per-narrative and peak memory are measured there and
reported from there, whatever the training hardware was.

## Does this reopen the generative branch?

**Partly, and not enough to change [decision 009](009-dropping-the-generative-branch.md).**

That decision rested on two costs. The training cost argument now largely dissolves — LoRA
tuning Qwen3 0.6B is under an hour and about a dollar on an A100.

But the disqualifying figure was **inference at 4–5 seconds per narrative on the M1**, and a
training GPU does not touch it. A bank processing hundreds of thousands of complaints locally
still faces weeks of wall-clock. Decision 009 stands; its *basis* narrows to the inference
argument alone, which was always the stronger half.

If the premise ever changes to allow a GPU at inference time, that decision should be reopened,
and this paragraph is the note to whoever does it.

## Consequences that need handling

1. **`make repro` must still work for someone without a GPU.** The constitution requires every
   published number to regenerate from a clean checkout. The repro path will state the training
   step's hardware and expected runtime, and publish trained weights so the evaluation, attack
   and utility numbers can be regenerated without retraining. A repro that silently requires a
   rented A100 is not a repro.
2. **Existing M1-trained numbers are not mixed with GPU-trained ones.** Hardware and precision
   differ, so the headline comparison is regenerated on one platform rather than stitched across
   two. Where an old number is kept, it says which hardware produced it.
3. **The GPU is rented and paid for by the human.** No provisioning, payment, or data upload
   happens automatically as part of this project's scripts.
4. **`docs/08-limitations.md` records the premise change**, so a reader is not misled into
   thinking the whole pipeline was built on a laptop.
