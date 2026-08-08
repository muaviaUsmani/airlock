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

### On real prose, the claim does not hold

2,492 real narratives, 10,543 spans, no carrier templates anywhere in the text
([decision 008](../DECISIONS/008-the-transfer-metric-was-invalid.md)):

| method | recall | precision | F1 | category accuracy |
|---|---:|---:|---:|---:|
| presidio | **77.4%** | 52.7% | 62.7% | n/a |
| **encoder** | 59.7% | **94.6%** | **73.2%** | **99.6%** |
| spacy | 43.5% | 17.6% | 25.0% | n/a |
| regex | 3.5% | 7.4% | 4.8% | n/a |

The encoder wins F1 and precision by a wide margin and labels almost perfectly when it fires.
**Presidio finds more.** And encoder recall falls from **90.1% on injected text to 59.7% on real
prose** — a 30-point drop that is the honest size of the synthetic-to-real gap.

### The categories Airlock was built for

| category | tier | n | encoder | presidio | spacy |
|---|---:|---:|---:|---:|---:|
| ORG_THIRD_PARTY | 2 | 647 | **0.8%** | 0.5% | 75.4% |
| LOCATION_FINE | 2 | 87 | 56.3% | 85.1% | 87.4% |
| PROTECTED_ATTR | 2 | 56 | **53.6%** | 21.4% | 21.4% |
| PERSON | 1 | 425 | 50.8% | 97.4% | 97.4% |
| TEMPORAL | 3 | 380 | **7.9%** | 97.1% | 97.4% |
| DATE | 3 | 7,607 | 69.9% | 89.8% | 35.7% |

`ORG_THIRD_PARTY` at 0.8% on 647 spans is a well-powered failure. `TEMPORAL` at 7.9% is another.
`PERSON` at 50.8% against 97.4% is a third, on the easiest category there is. Only
`PROTECTED_ATTR` shows the hoped-for pattern.

Categories below about n=50 — `RELATIONSHIP` (16), `LIFE_EVENT` (9), `EMPLOYER` (9), `HEALTH`
(3), `GOV_ID` (2) — support no claim in either direction and are shown only so the table is not
silently truncated. `DATE` is 7,607 of 10,543 spans, so the aggregate row is mostly about dates.

### Why, as far as the evidence supports

The encoder learned **category-specific carrier contexts**, not the entity types.

`ORG_THIRD_PARTY` surrogates come from the same ten bank names it trained on, so the failure is
contextual rather than lexical. Trained on *"I also contacted Citibank to see if they could
help"*, it does not recognise the same name in prose a customer actually wrote.

**Which means the held-out-template control was not sufficient.** It showed an 8.7-point gap and
looked reassuring, but every template in that set was written by the same generator in the same
register. Held-out templates test memorisation of specific strings. They do not test transfer to
a different author. Real prose was the only test that could catch this, and it did.

The prime suspect is the **injector**, not the architecture — which makes the generative branch
a more interesting experiment than it was, because it would separate "this architecture" from
"this training data".

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
