# 016 — A span-emitting writer: proposed, not built

**Date:** 2026-08-09
**Status:** **Open.** Surfaced under constitution principle I, not resolved.
Nothing in this file has been measured; every number in it is a prediction.
**Blocks:** nothing today. Relevant to any future M7 and to how the M3 writer
row is described.

---

## Why this is being written down

The writer arm was measured on 2026-08-09 and lost decisively:

| | writer Qwen3 0.6B | micro 70.7M |
|---|---:|---:|
| recall | 50.9% | 76.0% |
| precision | **99.5%** | 97.6% |
| F1 | 67.4% | **85.5%** |
| unparseable output | **26.3%** | n/a |
| ms/narrative | 3,590 | **4.5** |

Read quickly, that says generative redaction does not work. But the two failures
have a common cause that is **not the model**, and saying "the generative
approach loses" without recording that would be the kind of tidy conclusion this
project is supposed to distrust.

## The observation

**The writer has the highest precision of any arm in the project** — 99.5%, with
26 false positives against micro's ~200. When it decides something is personal
information, it is right essentially always.

Its recall is halved by something else entirely: **26.3% of outputs could not be
aligned to the input at all**, and per [decision 006](006-model-architecture.md)
an unalignable output contributes no spans. So a quarter of the corpus scores as
"redacted nothing" — not because the model failed to find PII, but because it
failed to faithfully reproduce a 365-token document while marking it up.

The cost has the same root. The writer regenerates the entire narrative to mark
a handful of spans: a median of ~365 decode steps to emit information that would
fit in ~30.

This was checked before being believed. The obvious alternative explanation was
that the harness truncated long inputs or outputs — `max_length=1024` and
`max_new_tokens=1400`. Measured against the real tokenizer on the evaluation set:
**0.1% of prompts exceed 1024 tokens and 0% of outputs would exceed 1400**
(median prompt 365, p90 551, max 1094). The failure is the model's, and it is
specifically a *document-reproduction* failure.

## The proposal

An arm that emits **span offsets or the PII substrings**, not a rewritten
document. Same base model, same LoRA recipe, same training data — only the
output format changes.

Predicted consequences, none of them measured:

1. **The 26.3% unparseable rate should go to approximately zero.** A model that
   never rewrites the document cannot corrupt it. Failures become malformed span
   lists, which are recoverable and countable rather than silently total.
2. **~13× fewer decode tokens** (~30 against ~365). Stacked with bf16 (measured
   1.4×) and a serving runtime such as vLLM (typically 5–10×), 3,590 ms/narrative
   would plausibly land at **35–50 ms**.
3. **The ranking probably does not change.** Even at 40 ms the writer is ~9×
   slower and ~150× more expensive per complaint than micro. The honest revised
   claim is that the architectural gap is roughly **10×, not 690×**.
4. **Precision may not survive the change.** The current 99.5% might depend on
   the model seeing its own reconstruction in context. That is a real risk to the
   hypothesis, not a footnote.

## Why this is a new arm and not an optimisation

Tempting to file this as "make the writer faster". It is not.

Changing the output format changes what the model is asked to do, which changes
what the numbers mean. Publishing the result as *the writer, optimised* would
quietly substitute one system for another underneath a published row — the exact
move constitution principle I exists to prevent.

If built, it is an additional arm, published alongside the document-rewriting
writer, with both rows visible. The rewriting writer's 26.3% drift is a genuine
finding about generative redaction and does not get deleted by a successor.

## Cost, so it can be decided rather than drifted into

- one LoRA training run, ~1 GPU-hour, ~$0.20 at the rate used here
- evaluation reuses `m3_compare_arms.py` unchanged
- a new `predict` implementation and its tests, since span parsing replaces
  `recover()`'s difflib alignment entirely

## What would make the comparison fair

The current writer's 3,590 ms/narrative is **not** an architectural floor — it is
one bucketed, batch-12, fp32 implementation, and the same code measured
11,400 ms/narrative earlier the same day before length-bucketing. Before any
"generative costs N× more" claim is published, the *existing* writer needs the
same optimisation effort the encoders received. Otherwise the comparison
measures how much attention each arm got, which is what
[HANDOFF §5](../HANDOFF.md) already flagged for the training-cost figure and
what this file flags for the inference figure.
