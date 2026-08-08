# What was trained, and why that architecture

**Status: branch A (encoder) is trained and measured. The result does not support the project's
central claim, and this page says so before it says anything else.**

---

## The fork, and what M1 did to it

The brief left the architecture open:

> *A small encoder built for marking spans of text (DeBERTa-class, ~100–300M parameters) versus a
> small generative model (Qwen3 0.6B / 1.7B class) prompted or tuned to produce the redacted
> text.*

M1 changed the question before it was answered. Because a model **cannot be trained on the real
CFPB text** — it contains `XXXX` where the personal information used to be, so a model fitted to
it learns `XXXX → redact` and is worthless on text where no such token exists — training has to
happen on injected data.

So the fork is not *"which architecture scores better on the corpus"*. It is:

> **Which architecture learns from synthetic injected data and transfers to real text?**

Transfer is the axis. An architecture that fits the injected distribution slightly better but
transfers worse is the wrong answer, and a comparison reporting only in-distribution scores would
never reveal it.

Resolved in [decision 006](../DECISIONS/006-model-architecture.md): **build both, encoder first.**

---

## The arms

Four, differing on two axes — **capacity** (how big) and **architecture** (how it works). Scaling
one does not answer the other's question, which is why both are run.

| arm | model | params | axis |
|---|---|---:|---|
| micro | `deberta-v3-xsmall` | 22M | capacity — the laptop-demo claim |
| *base* | `deberta-v3-base` | 184M | *capacity waypoint — [details in 04a](04a-base-encoder.md), not a deliverable* |
| large | `deberta-v3-large` | 434M | capacity — what staying small costs |
| generative | `Qwen3-0.6B` + LoRA | 600M | **architecture** — reopened by [decision 012](../DECISIONS/012-the-premise-is-a-trust-boundary-not-a-laptop.md) |

`base` was the first architecture trained and produced every methodological finding in this
project, but it is a waypoint rather than an output. Its full results, what it taught, and an
exact rebuild recipe are in **[docs/04a-base-encoder.md](04a-base-encoder.md)**.

At 600M against large's 434M, the generative arm is close to **size-matched** with the biggest
encoder — so the comparison isolates architecture rather than confounding it with capacity.

---

## Branch A — the encoder

| | |
|---|---|
| base | `microsoft/deberta-v3-base` |
| parameters | ~184M |
| task | token classification, BIO over the 16 categories in [DEFINITIONS.md](../DEFINITIONS.md) |
| labels | 33 (`O` plus `B-`/`I-` per category) |
| training data | 15,000 injected narratives, 61,483 spans |
| training hardware | rented RTX 3090, 24GB ([decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md)) |
| inference hardware | **M1 MacBook, 16GB, no GPU** — where the claim is measured |
| on disk | 376 MB |

**Why an encoder can do this at all.** Marking which parts of a text are personal information is
a per-token decision over a fixed label set — exactly what a token classifier is built for. One
forward pass, one label per token, no generation. It cannot hallucinate text it was not given,
and its character offsets come from the tokenizer rather than from the model's own arithmetic.

That last point is not incidental. It is the reason
[decision 006](../DECISIONS/006-model-architecture.md) rejected asking a small generative model
for JSON offsets: small models see tokens, not characters, so counting characters is arithmetic
rather than language, and the measurement would report the model's counting ability as much as
its ability to find personal information.

---

## The two shortcuts this design has to defeat

Both are versions of one failure: a model scoring well by learning something other than what
personal information looks like.

### 1. `XXXX → redact`

Established at M1. Real CFPB text marks its own answers, so it cannot be a training substrate.
**Consequence:** all training happens on injected data.

### 2. Learning the carrier phrasing

The injector splices personal information into clean narratives inside carrier sentences. Those
sentences are formulaic, so a model can memorise the phrasing rather than the content — the same
shortcut, one level up, and it would produce excellent scores that mean nothing.

**Consequence:** three controls, built into the data rather than checked afterwards.

| control | what it prevents |
|---|---|
| **Disjoint narratives** | 15,000 training narratives, 4,000 evaluation, no overlap, split before generation |
| **Disjoint templates** | six carrier templates per category — four for training, two held out for evaluation, asserted non-overlapping |
| **`seen_templates` control set** | the *same* evaluation narratives rendered with *training* templates |

That third one is the diagnostic. A model that scores well on `seen_templates` and badly on
`stratified` has memorised phrasing. The gap between them is published as a headline number
whatever it says.

**And the tiebreak:** transfer to real CFPB marked text, which contains no injected templates at
all, so no performance there can be explained by memorisation.

### A leak the assertions actually caught

The narrative-split assertion failed on its first run. **17.3% of clean narratives are exact
duplicates** — form-letter complaints submitted en masse, one appearing **181 times**. Without
deduplication, identical documents would have sat in both training and evaluation and the model
would have been scored on memorised text.

It was caught by an assertion rather than by inspection, which is the argument for asserting the
split rather than trusting it.

*(Checked whether this contaminates M1: it does not. Duplicates are 0.7% of the M1 sample and
1.3% of the marked corpus, against 17.3% of clean narratives — form letters are boilerplate with
no personal information, so there was nothing for a redactor to mark.)*

---

## A bug worth recording, because it fails silently

The first training run produced `nan` loss from the first optimiser step.

DeBERTa NaN'd; `roberta-base` trained cleanly on identical data. That reads as an architecture or
a Metal problem. It was neither — the same NaN appears on **CPU**, with an identical loss and
gradient norm, so it was deterministic rather than hardware.

Gradients were finite after `backward()`. Every parameter went non-finite after `step()`. The
tell was the loss itself: exactly **4.8046875**, which is exactly representable in fp16.

**transformers 5.x loads a checkpoint in the dtype it was saved in, and the `deberta-v3-base`
checkpoint on the Hub is stored in float16.** Pure fp16 AdamW underflows against `eps` and
destroys every weight on the first update. `roberta-base` only looked healthy because its
checkpoint happens to ship fp32.

The fix is one argument — `dtype=torch.float32` — plus an assertion so it cannot regress.

It is recorded here because of *how* it fails. Without the check, the run completes, saves a
376MB model, and reports plausible-looking numbers from a model that learned nothing. Chasing the
RoBERTa red herring would have quietly swapped the architecture to work around a bug that was
never there.

### And the environment underneath it

The virtual environment was **x86_64 running under Rosetta** on an arm64 machine, which caps
torch at 2.2.2 — below what transformers 5.x requires — and provides no real Metal acceleration.
A project whose entire premise is *"runs on an M1 laptop"* was not running on the M1. Rebuilt
native: torch 2.13.0, MPS available. `requirements.txt` records the constraint.

---

## Results

### On injected data, the encoder wins comfortably

`stratified` — held-out carrier templates, equal power per category:

| method | recall | precision | F1 |
|---|---:|---:|---:|
| **encoder** | **90.1%** | **96.8%** | **93.3%** |
| presidio | 46.2% | 47.7% | 46.9% |
| spacy | 54.9% | 35.6% | 43.2% |
| regex | 17.4% | 57.3% | 26.7% |

Note the regex row. At M1, scored against the `XXXX` markers, it was **0.0% by construction** —
a card-number pattern looks for digits and a marker is the letter X. Here it scores 17.4%. That
is [decision 004](../DECISIONS/004-two-injection-distributions.md) paying off: injected data can
score a whole method class the free labels physically cannot.

### The template-memorisation gap

| | encoder recall |
|---|---:|
| `seen_templates` (training phrasings) | 98.8% |
| `stratified` (held-out phrasings) | 90.1% |
| **gap** | **8.7 pts** |

A modest gap, which at the time read as good news. It was not, and the reason is below.

### On real prose — the first result, before the injector was rebuilt

2,492 real narratives, 10,543 spans, no carrier templates anywhere in the text
([decision 008](../DECISIONS/008-the-transfer-metric-was-invalid.md)). Encoder trained on the
**authored** carriers, three seeds:

| method | recall | precision | F1 |
|---|---:|---:|---:|
| presidio | **77.9%** | 52.8% | 62.9% |
| encoder (authored) | 47.3% ±17.1 | 94.9% ±1.8 | 62.0% ±15.9 |
| spacy | 44.1% | 17.8% | 25.3% |
| regex | 3.5% | 7.4% | 4.8% |

`ORG_THIRD_PARTY` — a tier 2 category, the kind this project exists for — scored **0.1%**.

**Look at the ± before anything else.** Recall varies by ±17.1 points across seeds. A single run
could have landed anywhere from ~30% to ~64%, and the project had been reporting n=1 numbers up
to this point. That spread is the strongest argument in the repository for the seed sweep, and
it was invisible until [decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md) made a
second seed affordable.

### After rebuilding the injector

Same architecture, same hyper-parameters, same test set. **Only the training data changed**
([decision 010](../DECISIONS/010-hardening-the-injector.md)):

| method | recall | precision | F1 | category accuracy |
|---|---:|---:|---:|---:|
| **encoder (hardened)** | 70.5% ±1.0 | **97.5% ±1.0** | **81.8% ±0.5** | 99.2% |
| presidio | **77.9%** | 52.8% | 62.9% | n/a |
| encoder (authored) | 47.3% ±17.1 | 94.9% ±1.8 | 62.0% ±15.9 | 99.6% |
| spacy | 44.1% | 17.8% | 25.3% | n/a |
| regex | 3.5% | 7.4% | 4.8% | n/a |

**F1 81.8% against Presidio's 62.9%**, driven by precision — 97.5% against 52.8%. When this
model marks something, it is almost always right, and right about what it is (99.2% category
accuracy).

**Presidio still finds more.** 77.9% recall against 70.5%. That row is published because it is
the honest shape of the result: Airlock is the better redactor by F1 and by precision, and it is
not the better *detector* by recall.

**The variance collapsed**: ±17.1 → ±1.0 on recall, ±15.9 → ±0.5 on F1. The hardened data does
not just train a better model, it trains a *stable* one. That is arguably the more important
finding, because a method whose quality depends on the seed is not a method.

### Per category — and the one row that proves the diagnosis

| category | n | presidio | spacy | authored | **hardened** | delta |
|---|---:|---:|---:|---:|---:|---:|
| ORG_THIRD_PARTY | 647 | 5.7% | 78.8% | 0.1% | **45.0%** | **+44.9** |
| PERSON | 425 | 97.2% | 97.2% | 33.3% | **65.5%** | +32.2 |
| AMOUNT | 246 | 0.8% | 84.6% | 38.2% | **65.7%** | +27.5 |
| DATE | 7,607 | 90.3% | 36.6% | 55.3% | **78.9%** | +23.7 |
| LOCATION_FINE | 87 | 85.1% | 87.4% | 46.4% | **68.6%** | +22.2 |
| EMPLOYER | 9 | 11.1% | 88.9% | 40.7% | 59.3% | +18.5 |
| ACCOUNT_ID | 714 | 20.2% | 23.8% | 24.9% | **41.2%** | +16.3 |
| PROTECTED_ATTR | 56 | 12.5% | 12.5% | 39.9% | **53.0%** | +13.1 |
| CASE_REF | 176 | 98.9% | 30.1% | 78.4% | 87.3% | +8.9 |
| CONTACT | 122 | 92.6% | 6.6% | 77.6% | 81.1% | +3.6 |
| MERCHANT | 44 | 20.5% | 97.7% | 85.6% | 88.6% | +3.0 |
| **TEMPORAL** | **380** | **96.8%** | **96.8%** | **6.6%** | **3.1%** | **−3.5** |
| RELATIONSHIP | 16 | 0.0% | 0.0% | 4.2% | 0.0% | −4.2 |

**`TEMPORAL` is the control nobody designed.** It is the one well-powered category that received
**no real carriers** — mining found none, and entity-site substitution does not cover weekdays or
times of day, so it kept its hand-authored templates. It is also the only well-powered category
that did not improve.

Treatment applied → large gains. Treatment not applied → nothing. That is close to a controlled
experiment, and it is the strongest evidence available that
[decision 008](../DECISIONS/008-the-transfer-metric-was-invalid.md) diagnosed the right cause:
the model was learning carrier contexts, not entity types.

It is also a standing failure. At 3.1% against 96.8% for both baselines, this model is useless
on times and weekdays, and `TEMPORAL` is a tier 3 quasi-identifier that feeds the M4 attack
directly.

### Where it still loses

Published because publishing the rows we lose is the point:

- **`PERSON` 65.5% against 97.2%.** The easiest category there is, and both baselines beat it.
- **`TEMPORAL` 3.1% against 96.8%.** Effectively blind.
- **`DATE`, `CASE_REF`, `CONTACT`** — Presidio wins each, by 4 to 12 points.
- **`ORG_THIRD_PARTY` 45.0% against spaCy's 78.8%** — a 45-point gain and still second.

Categories below about n=50 (`RELATIONSHIP` 16, `EMPLOYER` 9, `HEALTH` 3, `GOV_ID` 2) support no
claim in either direction. `DATE` is 7,607 of 10,543 spans, so the aggregate row is substantially
a statement about dates.

### Inference cost, measured on the M1

The claim is a model that runs on a laptop, so this is measured on the laptop
([decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md)) — not on the rented GPU that
trained it.

| | |
|---|---|
| throughput | **5.0 narratives/sec** (199 ms each) |
| peak process memory | 4.8 GB — fits 16 GB with room |
| model on disk | **744 MB** fp32, ~372 MB fp16 |

At 5/sec, 300,000 complaints is about **17 hours** on one laptop — an overnight job, not a
blocker.

**A correction to the README's framing.** The headline sentence said "a 300MB model". The
measured artifact is 744 MB in fp32 and would be ~372 MB in fp16. Neither is 300 MB. The
README now quotes the measured size.

---

---

## What gets compared, once both branches exist

1. **Recall, precision, category accuracy** per category on `stratified`.
2. **Aggregate scores** on the natural-frequency set.
3. **Transfer** to real CFPB marked text — the number that matters most.
4. **Template generalisation** — the `seen_templates` gap.
5. **Inference cost** — seconds per narrative on the M1, and peak memory. The claim is about a
   model that runs on a laptop, so speed is a result, not a footnote.
6. **Model size on disk.**

---

## Reproducing this

```bash
make m3
```

Training: 15,000 narratives, 3 epochs, batch 8 × 2 accumulation, lr 3e-5, max sequence length
384, seed `20260806`. Checkpoints after every epoch — on this hardware an epoch takes over two
hours, which is an expensive thing to discover you have not saved.
