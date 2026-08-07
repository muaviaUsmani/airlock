# 006 — Model architecture: build both, encoder first

**Date:** 2026-08-06
**Status:** Decided
**Blocks:** M3 (the model)
**Fork source:** Section 6 of the project brief, open fork #1
**Resolved under:** the standing instruction in
[the constitution](../.specify/memory/constitution.md), principle I

---

## The question

> *A small encoder built for marking spans of text (DeBERTa-class, ~100–300M parameters) versus
> a small generative model (Qwen3 0.6B / 1.7B class) prompted or tuned to produce the redacted
> text. Different failure modes, different speeds, different training cost. Not decided.*

## What M1 changed about this question

Worth stating, because it is not the question the brief asked.

M1 established that a model **cannot be trained on the marked CFPB text** — fitted to predict
`XXXX` positions in text that contains `XXXX`, it learns `XXXX → redact`, scores near-perfect
and is useless on real text. Training therefore happens on injected data.

So the fork is no longer *"which architecture scores better on the corpus"*. It is:

> **Which architecture learns from synthetic injected data and transfers to real text?**

Transfer is the axis. An architecture that fits the injected distribution slightly better but
transfers worse is the wrong choice, and a comparison that only reports in-distribution scores
would not reveal that.

## The decision

**Build both. Encoder first, then reassess with evidence.**

| | |
|---|---|
| **Branch A** | DeBERTa-v3-base token classifier (~184M), BIO tagging over the 16 categories |
| **Branch B** | Qwen3 0.6B, LoRA-tuned, emitting **inline tags** |

Sequential rather than parallel, because the encoder costs ~2 hours and the generative branch
5–10 hours plus 4–6 hours of inference. Running the cheap branch first means the shared data
pipeline is validated before the expensive branch spends the budget on it, and if the encoder
already loses badly to Presidio on tier 2 then that is the finding and the second run is
re-scoped rather than run out of completeness.

## The generative output format, and the two that were rejected

A generative model must emit *something*, and the choice changes both comparability and cost.

**Chosen — inline tags.** The model rewrites the narrative with markup:

```
I called <PERSON>Sarah</PERSON> at the <LOCATION_FINE>Fremont</LOCATION_FINE> branch
```

Spans are recovered by aligning output to input. Comparable to the encoder at span level,
natural as a generative task, and it carries category labels for free. Output runs about 1.2x
input length, so roughly 4–6 hours of inference over 4,000 narratives.

**Its risk, which the harness must handle rather than hide:** a generative model can silently
alter the text it is not tagging — fixing a typo, dropping a clause, rewording a sentence. If
the harness quietly accepts that, span offsets become fiction. So untagged content is verified
against the input, and any drift is **reported as a failure mode of the architecture**, not
repaired. Text drift is a real and interesting difference between the two branches and belongs
in the results.

### Rejected: full redacted text

The model emits the finished narrative with personal information already replaced.

This is what the brief's own wording describes, and it is the most realistic deployment shape —
closest to what a bank would actually run.

Rejected on two costs. Output is full input length, putting inference at **12–16 hours** rather
than 4–6. And span-level comparison against the encoder then requires diff-alignment between
original and redacted text, which is itself error-prone: a diff cannot always tell whether a
missing phrase was redacted or dropped. That uncertainty would land squarely on the head-to-head
comparison this whole exercise exists to produce.

Noted for later: this format is the right one for a deployment demo, and if the generative
branch wins on quality it is worth a small follow-up run to measure it in its natural shape.

### Rejected: span list as JSON

The model emits `[{start, end, category}]` directly.

Cheapest by a wide margin — output is short, so **2–3 hours** of inference — and directly
comparable to the encoder with no alignment step at all.

Rejected because character offsets are a known weak spot for small language models: they see
tokens, not characters, and counting characters is arithmetic rather than language. A meaningful
share of spans would land a few characters off. The measurement would then be reporting the
model's arithmetic as much as its ability to find personal information, which is an unfair test
of the architecture and would make the comparison meaningless in the direction that flatters the
encoder.

## What gets compared

Both branches report, on identical data:

1. **Recall, precision, category accuracy** on the `stratified` injected set, per category.
2. **Aggregate scores** on the `natural` set.
3. **Transfer** — recall against the real CFPB `XXXX` markers, the substrate neither was trained
   on. This is the number that matters most and the one M1 was built to compare against.
4. **Template generalisation** — see below.
5. **Inference cost** — seconds per narrative on the M1, no GPU, and peak memory. The project's
   claim is about a model that runs on a laptop, so speed is a result, not a footnote.
6. **Model size on disk**, against the README's "300MB" framing.

## The validity threat this decision has to name

The injector splices in carrier sentences from a fixed template set. A model trained on that data
can learn **the template** rather than the personal information — the same degenerate shortcut as
`XXXX → redact`, one level up, and it would produce excellent scores that mean nothing.

The mitigation is built into the harness rather than checked afterwards:

- **Templates are split disjointly.** Training data is generated from one set of carrier
  templates; the evaluation sets are generated from templates the model has never seen. A model
  that has memorised phrasing collapses on held-out templates, and the size of that collapse is
  published as a number.
- **Narratives are split too.** No clean narrative appears in both training and evaluation.
- **Transfer to real marked text is the tiebreak.** Real CFPB narratives contain no injected
  templates at all, so performance there cannot be explained by template memorisation.

If both architectures collapse on held-out templates, the honest conclusion is that this
injection design cannot train a transferable model, and that is the finding — it goes in the
README, and the injector is redesigned before any model claim is made.
