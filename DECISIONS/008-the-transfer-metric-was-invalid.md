# 008 — The transfer metric was invalid, and what replaced it found

**Date:** 2026-08-08
**Status:** Decided. Amends [decision 006](006-model-architecture.md).
**Blocks:** M3 conclusions, M4 (which redaction goes into the attack)
**Fork source:** Not in the brief. Surfaced by the M3 evaluation run.

---

## The metric I specified did not work

[Decision 006](006-model-architecture.md) named transfer to real CFPB text *"the number that
matters most"*. The first run produced:

| method | recall vs `XXXX` markers |
|---|---:|
| spacy | 68.5% |
| presidio | 60.7% |
| **encoder** | **0.9%** |
| regex | 0.0% |

Read quickly that says the encoder does not transfer. It says nothing of the kind.

**In published CFPB text the personal information has already been removed.** It was replaced by
`XXXX`. There is no name left to find. To score against those markers a method must flag the
marker itself — and flagging `XXXX` is precisely the degenerate `XXXX → redact` behaviour that
M1 established must never be learned.

The evidence is unambiguous. Across 3,000 narratives the encoder predicted **260 spans total**,
against 15,839 on injected text. It ignores `XXXX` because it was trained on text where personal
information has real surface forms. Presidio and spaCy score well because spaCy's NER tags a
capitalised `XXXX` as an entity from surrounding context.

**The metric rewarded the shortcut and punished correct behaviour.** It is withdrawn.

## What replaced it

`scripts/m3_transfer_surrogate.py`. Real prose, real redaction sites, realistic surface forms:

1. Take real marked narratives.
2. Estimate each marker's category from surviving context.
3. Replace the marker with a plausible **surrogate** of that category — `XXXX` becomes
   `Sarah Mendez`, or `$47.13`.
4. Record exact positions while building, single forward pass, asserted.
5. Score every method on those positions.

The result is text a human wrote, redacted where a human decided personal information was,
refilled with values whose positions we know exactly — and containing **none of the injector's
carrier templates**, so nothing scored there can be explained by template memorisation.

Limitations, reported rather than hidden: only the ~46.5% of markers whose category context can
estimate are filled, the rest stay `XXXX` and are never scored either way, predictions touching
an unfilled marker are dropped from the false-positive count, and a category estimated wrongly
puts the wrong surrogate in and tests the wrong thing.

## What it found, and it is not what the project hoped

2,492 real narratives, 10,543 scored spans.

| method | recall | precision | F1 | category accuracy |
|---|---:|---:|---:|---:|
| presidio | **77.4%** | 52.7% | 62.7% | n/a |
| **encoder** | 59.7% | **94.6%** | **73.2%** | **99.6%** |
| spacy | 43.5% | 17.6% | 25.0% | n/a |
| regex | 3.5% | 7.4% | 4.8% | n/a |

**The encoder does not dominate on real prose.** It wins F1 and precision by a wide margin, and
its category accuracy is near perfect — when it marks something it is almost always right about
what it is. But **Presidio finds more**, 77.4% against 59.7%.

And the encoder's recall falls from **90.1% on injected text to 59.7% on real prose**. A 30-point
drop is the honest size of the synthetic-to-real gap.

### The part that contradicts the project's central claim

Airlock exists to beat the baselines on **tier 2 contextual identifiers**. On real prose it does
not:

| category | tier | n | encoder | presidio | spacy |
|---|---:|---:|---:|---:|---:|
| ORG_THIRD_PARTY | 2 | 647 | **0.8%** | 0.5% | 75.4% |
| RELATIONSHIP | 2 | 16 | 6.2% | 0.0% | 0.0% |
| LOCATION_FINE | 2 | 87 | 56.3% | 85.1% | 87.4% |
| PROTECTED_ATTR | 2 | 56 | **53.6%** | 21.4% | 21.4% |
| PERSON | 1 | 425 | 50.8% | 97.4% | 97.4% |
| TEMPORAL | 3 | 380 | **7.9%** | 97.1% | 97.4% |
| DATE | 3 | 7,607 | 69.9% | 89.8% | 35.7% |

`ORG_THIRD_PARTY` at 0.8% on 647 spans is a well-powered, unambiguous failure. `TEMPORAL` at
7.9% on 380 spans is another. `PERSON` at 50.8% against Presidio's 97.4% is a third, on the
easiest category there is.

Only `PROTECTED_ATTR` shows the hoped-for pattern — the encoder at 53.6% against 21.4% for both
baselines.

**Categories with n below ~50 are not evidence of anything.** `RELATIONSHIP` (16), `LIFE_EVENT`
(9), `EMPLOYER` (9), `HEALTH` (3), `GOV_ID` (2) are too small to support a claim in either
direction, and are reported only so the table is not silently truncated. Note also that `DATE` is
7,607 of 10,543 spans, so the aggregate row is mostly a statement about dates.

## Why it fails, as far as the evidence supports

The encoder learned **category-specific carrier contexts**, not the entity types themselves.

`ORG_THIRD_PARTY` surrogates are drawn from the same ten bank names the model trained on, so the
failure is not lexical — it is contextual. Trained on *"I also contacted Citibank to see if they
could help"*, it does not recognise the same name in prose a customer actually wrote. `TEMPORAL`
behaves the same way: trained on *"It was a Tuesday and I called at 2pm"*, it misses weekdays
elsewhere.

**This means the held-out-template control was not sufficient**, and that is worth stating
plainly. `stratified` used templates the model never saw, and showed only an 8.7-point gap. But
every template in that set was written by the same generator in the same register. Held-out
templates test memorisation of specific strings; they do not test transfer to a different author.
**Real prose was the only test that could reveal this, and it revealed it.**

## Consequences

1. **The M3 claim is not earned as stated.** The README reports that Airlock wins precision, F1
   and category accuracy, loses recall to Presidio, and fails on the contextual categories it was
   built for. That goes above the fold, not in a footnote.
2. **The marker-based transfer number is deleted, not published.** It measures the wrong thing;
   publishing it with a caveat would still put a wrong number in circulation.
3. **M4 still runs with the encoder.** Its redaction is real and its precision is high; what
   the attack measures is what survives, and that is worth knowing whatever the span scores say.
4. **The injector is the prime suspect for a fix**, not the architecture. Carrier templates that
   vary only in phrasing, all written in one register, teach context that does not exist outside
   them. Whether the generative branch shares the weakness is now a much more interesting
   question than it was, because it would separate "this architecture" from "this training data".
