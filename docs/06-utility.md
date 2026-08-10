# Is the redacted text still worth anything?

**Status: M5 complete. Every number here comes from `make m5`
(`results/m5_utility.txt`).**

---

## Why this milestone has to exist

M4 reports re-identification falling from **36.9% to 0.2%**. Read on its own,
that number rewards destruction: blank every narrative and nothing leaks at all.
spaCy scoring 0.0% re-identification is exactly that — it wins the leakage column
by removing five times more text than it should.

So leakage is only half a result. The other half is whether anything survives
that a bank would still have wanted to read. That is what this milestone
measures, and it is the reason the headline is a *trade* rather than a rate.

## How usefulness is measured without a human judging anything

The CFPB publishes structured fields alongside each narrative, filled in by the
CFPB's own intake process rather than by us. Those fields are an answer key that
already exists:

| field | question asked of the reader |
|---|---|
| `Sub-product` | what kind of credit card account is this about? |
| `Issue` | what is the customer's main complaint? |
| `Company response to consumer` | did the company give the customer money back? |

A cheap frontier model (Haiku, temperature 0) reads each narrative — raw, or
redacted by each method — and answers. Accuracy is scored against the CFPB's
fields. No human grades anything and no model judges another model, which is
what the constitution requires of every headline number.

**The reader is deliberately cheap.** This measures what the *redaction* costs,
not how clever the reader is. A stronger model would infer around the gaps and
flatter the redactor, blurring the very difference being measured.

## The result

233 complaints, graded against the CFPB's own fields:

| method | overall | sub_product | issue | relief |
|---|---:|---:|---:|---:|
| raw (no redaction) | **48.0%** | 71.5% | 22.3% | 52.8% |
| presidio | 44.4% | 72.0% | 20.6% | 43.8% |
| **airlock:micro** | **47.3%** | 73.4% | 21.5% | 49.8% |
| airlock:base2 | 46.7% | 73.4% | 20.6% | 48.9% |
| spacy | 38.9% | 53.1% | 21.9% | 43.3% |
| *majority-class baseline* | | *86.0%* | *12.0%* | *88.4%* |

And the trade the project exists to quantify:

| method | re-identified | utility | utility lost |
|---|---:|---:|---:|
| raw | 36.9% | 48.0% | 0.0 |
| presidio | 1.2% | 44.4% | 3.6 |
| **airlock:micro** | **0.2%** | 47.3% | **0.7** |
| airlock:base2 | 0.2% | 46.7% | 1.3 |
| spacy | 0.0% | 38.9% | 9.1 |

**Airlock is the best trade available here.** It removes more re-identifying
information than Presidio (0.2% against 1.2%) while costing a fifth as much
usefulness (0.7 points against 3.6). spaCy demonstrates the failure mode the
whole milestone was built to catch: it wins the leakage column outright, at 0.0%,
by destroying 9.1 points of utility — thirteen times Airlock's damage.

## The part that undercuts these numbers, stated plainly

**Two of the three questions sit below their own majority-class baseline.** On
`sub_product` a reader that ignored the text entirely and always guessed the
common answer would score 86.0%; the best actual reader manages 73.4%. On
`relief` the baseline is 88.4% and the best score is 52.8%.

That means those two questions are not measuring comprehension. They are mostly
measuring how often the reader is talked out of the base rate. Only `issue`
(22.3% against a 12.0% baseline) carries real signal, and it is the noisiest of
the three.

Publishing them anyway, with the baselines next to them, is the point:
constitution principle IV says a question that turns out not to measure anything
is a finding, and belongs in the table rather than in a deleted line of code.

**Consequence for the trade table:** the absolute utility figures are compressed
by this weak floor, so "48.0% utility" should not be read as "the text is 48%
useful". The *differences between methods* are what carry the argument, because
every method faces the identical floor.

## Three bugs found here, all of which looked like results

Every one of these produced a plausible low score rather than an error. They are
listed because the pattern matters more than the individual fixes.

1. **A blank answer key scored as a wrong answer.** 8.4% of the corpus has no
   `Sub-product`. `str(nan)` is `"nan"`, so those rows had the literal string
   `"nan"` as their correct answer — and `"nan"` was offered to the reader as a
   valid multiple-choice option on every row. Fixed: rows with no answer key are
   excluded from that question's denominator.
2. **An option list that hid two thirds of the correct answers.** `issue`
   offered twelve labels chosen as `sorted(...)[:12]` — the first twelve
   *alphabetically* out of 27. Only 32.6% of true answers were among them; the
   two most common were excluded for beginning with "P" and "O". The question was
   capped at 32.6% before the reader saw a word. Fixed: every label present is
   offered.
3. **A question whose answer is never in the text.** `Company response to
   consumer` is recorded *after* the complaint is filed. A narrative written
   beforehand cannot contain it, so the reader correctly answers UNKNOWN and is
   marked wrong. Kept, and reported against its baseline, because the finding is
   that the question is unanswerable — not that redaction broke it.

The script now asserts the invariant that made all three possible:

> a correct answer must always be among the options offered

and prints the achievable ceiling whenever it is not.

## What this milestone does not establish

- **The re-identification column is not per-arm.** M4 measured one arm, so both
  `airlock:micro` and `airlock:base2` currently show the same 0.2%. It should not
  be read as if the two had been attacked separately.
- **233 complaints is a small sample.** Differences of a point or two between
  methods are not resolvable at this size; the spaCy gap is.
- **One reader, one prompt, one temperature.** A different reader would move all
  the absolute numbers. The comparison is internally consistent, not universal.

---

Next: [what this project does not do](08-limitations.md).
