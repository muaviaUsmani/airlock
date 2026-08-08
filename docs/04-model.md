# What was trained, and why that architecture

**Status: M3 in progress. Branch A (encoder) is training. Numbers appear here only once a
committed script has produced them.**

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

## Branch A — the encoder

| | |
|---|---|
| base | `microsoft/deberta-v3-base` |
| parameters | ~184M |
| task | token classification, BIO over the 16 categories in [DEFINITIONS.md](../DEFINITIONS.md) |
| labels | 33 (`O` plus `B-`/`I-` per category) |
| training data | 15,000 injected narratives, 61,483 spans |
| hardware | M1 MacBook, 16GB, MPS, no GPU |
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
