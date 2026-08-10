# Airlock

**A 291MB model that strips personal information out of bank complaint text — and
an attack that measures whether the customer can still be identified afterwards.**

The redaction is the boring half. The measurement is the project.

---

## 1. What this is

A bank has hundreds of thousands of written customer complaints and wants a
frontier model to analyse them. It cannot send them out, because the text is full
of personal information. So something has to strip that out first — and that
something has to run inside the company's own infrastructure, because of a
constraint that sounds circular until you sit with it:

> *If you could send the text out to be checked, you would not have needed to
> check it.*

Airlock is that something: a small encoder that runs wherever the company's
boundary is, small enough that a laptop is a reasonable floor to quote.

**But anyone can claim they removed the personal information.** Airlock's actual
subject is whether that claim survives contact with an adversary. It builds a
synthetic transaction database, redacts the complaints, then **attacks its own
output** — taking the redacted text and trying to find the one customer it
belongs to.

Two findings from that setup explain why the project exists at all:

- **Names are not what identifies people.** In the synthetic database an exact
  date identifies nobody (479 customers share one) and a merchant identifies
  nobody (1,329 do). Put an amount, a date and a merchant together and you reach
  **99.7% uniqueness**. None of those three is personal information. No PII
  detector removes any of them.
- **Professional redactors already miss this.** The CFPB's own trained staff,
  working to a published standard, leave an intact dollar amount in **44.2%** of
  narratives — the single strongest join key against a transaction database.

**This was built as a learning exercise, not a product.** That framing is load
bearing: the goal was to build every branch of each fork and publish the
comparison, rather than to ship one tuned artifact. The most valuable output is
[what it taught us](docs/09-lessons.md) — which includes a headline we nearly
published that turned out to be measuring our own mistake.

**→ [Setup and how to run it](docs/00-setup.md)** — Mac, GPU, Docker, and the one
API key.

---

## 2. The case study

### What we set out to do

Answer one question honestly: *after we redact a complaint, can the customer
still be identified?* Six milestones — characterise the corpus, measure existing
tools, build an injection harness and an adversary, train a model, attack it,
then check the redacted text is still worth reading.

### The pivots, and why each happened

**The free labels could not evaluate the thing we cared about.** The CFPB corpus
has personal information already replaced by `XXXX` markers. That looks like a
free labelled dataset and is a trap: a model trained on it learns `XXXX → redact`
and is worthless on text where no such token exists. Worse, when we scored
methods against those markers, plain regex got **0.0% structurally** — a
card-number pattern looks for digits and a marker is letters, so no pattern can
ever match one. We had to build a synthetic injection harness to get a
like-for-like comparison at all.

**The frequencies we injected turned out to decide the headline.** Running the
same attack on the same narratives with the same attacker, and changing only
where the injection frequencies came from, moved re-identification from **8.6% to
36.9%**. Markers record only what was *removed*; the fields that enable
re-identification are precisely the ones nobody removes. That is
[decision 007](DECISIONS/007-tier3-frequencies-cannot-come-from-markers.md), and
it is the single largest swing in the project.

**"Runs on a laptop" was the wrong constraint.** We started with a hard laptop
ceiling, which quietly ruled out larger models and killed the generative branch
on cost. [Decision 012](DECISIONS/012-the-premise-is-a-trust-boundary-not-a-laptop.md)
replaced it with "runs inside the company's trust boundary" — which is what the
privacy argument actually needs. That reopened both the larger encoders and the
generative arm, and moved training to a rented GPU
([decision 011](DECISIONS/011-training-moves-to-rented-gpu.md)).

**A transfer test we had already published was invalid.** Scoring on real CFPB
text against `XXXX` markers rewarded exactly the degenerate behaviour we had
banned. We threw the metric out and rebuilt it as a surrogate set — real prose,
real redaction sites, plausible synthetic values
([decision 008](DECISIONS/008-the-transfer-metric-was-invalid.md)).

### Why we built every fork instead of picking one

The standing rule was *build every branch, publish the comparison, do not pick
one and discard the rest*. That is more expensive and it repeatedly paid:

- Four architectures — micro, base, large, and a generative writer — instead of
  one. The writer lost on F1 but has **the highest precision of any arm (99.5%)**,
  which is a real result we would not otherwise have had.
- Two injection distributions instead of one, which is what exposed the
  frequency-source problem above.
- Three seeds per arm rather than one. An earlier single-seed sweep reported an
  arm's recall varying by **±17 points** — a number a single run would have
  published as a finding.

The cost was real: about 24 GPU-hours and **$4.62**. The comparison is the
deliverable, not the winning arm.

### What broke in our own method

Seven separate defects, and the pattern matters more than any one of them:
**almost every one produced a plausible number rather than an error.** Nothing
crashed.

| what looked true | what was true |
|---|---|
| A 70.7M model beats a 434M one by 5 F1 | We gave three model sizes one training schedule. The big ones had memorised the data by epoch 2 and we trained a third. Retrained for one epoch, **the ranking inverts.** |
| Presidio and spaCy score 0.0% on every category | They were never run. The report substituted `0` for a missing value. |
| The model uses 7 MB of memory on an M1 | It ran on a Linux GPU box, where `ru_maxrss` is kilobytes not bytes — a 1000× error — under a heading claiming the laptop. |
| Redaction destroys the ability to answer questions | Two of the three questions were unanswerable by construction; a third offered a multiple-choice list missing two thirds of the correct answers. |
| Generative redaction costs 690× more than an encoder | 9× of that was our own padding waste and another 2.6× an unnecessary fp32 load. The real gap is ~267×. |
| The model is 372MB | No file was ever that size. It was half of a *different* model's size, from a "what it would be if converted" line that lost its conditional. |
| We have per-milestone specs and plans in `specs/` | That directory does not exist and never did. |

Each is written up with its fix in [docs/09-lessons.md](docs/09-lessons.md).

**The one that matters most:** the M3 headline is not a finding about model size.
It is a finding about our training recipe — one learning rate across three
scales, a fixed three epochs, no validation split, no early stopping. The arms
were scored at different points on their own overfitting curves, and the bigger
the model, the further past its optimum we stopped
([decision 017](DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md)).

### What we left as educated guesses

Stated plainly, because pretending otherwise is the failure this project is about:

- **Which encoder is actually most accurate.** After the recipe problem surfaced,
  the honest answer is *we do not know*. The effect is smaller than the
  seed-to-seed spread (±0.5 to ±2.9 F1); resolving it needs roughly 30 seeds per
  arm — about **40 GPU-hours for the large arm alone**. We stopped and said so
  instead. The cost and size differences are not close, and they do survive.
- **The writer's cost floor.** We measured 1,200 ms/narrative after fair tuning.
  A serving runtime such as vLLM would plausibly give another 5–10×, and a
  span-emitting output format another ~13×, but neither was run — so both are
  labelled predictions ([decision 016](DECISIONS/016-span-emitting-writer-proposed.md)).
- **The M1 latency table.** Measured once informally at ~72 ms/narrative, but the
  committed table was produced on a GPU and now says so in its own heading. No M1
  figure is published until a laptop run is committed.
- **Utility beyond a cheap reader.** M5 uses one model, one prompt, one
  temperature. The comparison between methods is internally consistent; the
  absolute numbers would move under a different reader.
- **Whether 36.9% or 14.3% is "the" leakage rate.** Both are real.
  Re-identification is strongly population dependent — the same text scores 19.1%
  against 2,500 customers, 36.9% against 10,000 and 14.3% against 40,000. A
  leakage rate quoted without its database size is not a number.

### The numbers

**Redaction quality** — 2,492 real narratives, three seeds per arm:

| arm | recall | precision | F1 | throughput |
|---|---:|---:|---:|---:|
| micro 70.7M | 76.0% ±0.8 | 97.6% ±0.4 | **85.5% ±0.5** | 192/sec |
| base 184M | 68.0% ±3.6 | 97.3% ±1.7 | 80.0% ±2.9 | 155/sec |
| large 434M | 68.2% ±2.6 | 96.9% ±1.1 | 80.1% ±1.9 | 63/sec |
| writer 0.6B | 50.9% | **99.5%** | 67.4% | 0.8/sec |

*Read with the caveat above: the accuracy ranking reflects our training schedule,
not capacity. The throughput column does not.*

**The attack, and the trade** — leakage against usefulness, at a
10,000-customer database:

| method | re-identified | utility retained | utility lost |
|---|---:|---:|---:|
| no redaction | 36.9% | 48.0% | — |
| Presidio | 1.2% | 44.4% | 3.6 |
| **Airlock** | **0.2%** | **47.3%** | **0.7** |
| spaCy | 0.0% | 38.9% | 9.1 |

Airlock leaks less than Presidio at **one fifth** the cost in usefulness. spaCy
wins the leakage column outright — by destroying the text, which is exactly the
failure the utility axis exists to catch.

**What it cost to find out:** $4.62 of rented GPU, ~$4 of API credit, 24 hours of
compute, and about 16 GB of published artifacts.

---

## 3. Setup and running

Moved into its own document to keep this one readable.

**→ [docs/00-setup.md](docs/00-setup.md)**

The short version:

```bash
./scripts/bootstrap.sh    # venv + corpus
make weights              # published models, no AWS account needed
make repro-smoke          # ~3 min, proves the whole chain runs
make repro                # ~7 h, regenerates every number here
```

---

## 4. Technical details

TLDRs only. Each links to the document carrying the reasoning and the numbers.

**The corpus.** US CFPB consumer complaints — real text, already scrubbed to a
published standard, which is what makes it usable and what makes it awkward. The
source URL is a rolling snapshot with no versioning, so the exact bytes are
mirrored with a sha256. → [docs/02-data.md](docs/02-data.md)

**The baselines.** Presidio and spaCy measured before anything was built. Regex
scores 0.0% against the marker oracle *structurally*, which is why the comparison
had to move to injected data. → [docs/03-baselines.md](docs/03-baselines.md)

**The model.** `deberta-v3` at three scales plus a Qwen3-0.6B LoRA writer, all on
identical hardened training data so any difference is capacity — or, as it turned
out, schedule. → [docs/04-model.md](docs/04-model.md),
[docs/04a-base-encoder.md](docs/04a-base-encoder.md)

**The attack.** A synthetic transaction database and a linkage adversary.
Re-identification rate is the headline metric, not span F1, and it is reported at
three database sizes because it is population dependent.
→ [docs/05-attack.md](docs/05-attack.md)

**The utility axis.** A cheap frontier model answers questions about redacted
text, graded against the CFPB's own structured fields. Two of the three questions
turned out to carry almost no signal; they are published anyway, with their
baselines. → [docs/06-utility.md](docs/06-utility.md)

**The ablations.** Database size, the memorisation transfer curve, training-set
size, and epoch count. → [docs/07-ablations.md](docs/07-ablations.md)

**What this does not do.** → [docs/08-limitations.md](docs/08-limitations.md)

**What went wrong and what it taught us**, in plain language — the part most
worth reading. → [docs/09-lessons.md](docs/09-lessons.md)

**Definitions.** What counts as personal information, a correct removal, a
re-identification. Locked at M0. → [DEFINITIONS.md](DEFINITIONS.md)

**Decisions.** One file per fork, with the options considered and the reasoning
attached — including the ones later overturned. → [DECISIONS/](DECISIONS/)

**The rules that do not bend** — reproducibility, no secrets, negative results
get published, forks get surfaced rather than silently resolved.
→ [the constitution](.specify/memory/constitution.md)

There are **no per-milestone spec directories**, though the constitution's
workflow describes them and an earlier version of this README claimed they lived
in `specs/`. They do not exist and never did; the reasoning is in `DECISIONS/`
and the milestone docs instead. Recorded rather than quietly deleted, because a
README describing work that was never done is the same failure as a number that
was never measured.

---

## What this is not

- **Not a general-purpose PII detector.** Tuned to one domain. The narrowness is
  the argument, not a limitation to apologise for.
- **Not a compliance tool.** Nothing here satisfies any regulation, and nothing in
  this repository should be read as suggesting it does.
- **Not a benchmark of frontier models.** M5 uses one deliberately cheap reader to
  measure what the *redaction* costs, not how clever the reader is.
- **Not deployed.** No hosting, no service. The code is the artifact.
- **Not a claim that small models beat large ones.** We thought it was. It was a
  claim about our training schedule
  ([decision 017](DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md)).

---

## Milestones

| | milestone | status |
|---|---|---|
| **M0** | Characterise the corpus | **done** |
| **M1** | Measure the baselines | **done** |
| **M2** | Injection harness + adversary | **done** |
| **M3** | The model | **done** — four arms, three seeds each |
| **M4** | The attack | **done** — 36.9% → 0.2% at 10k customers |
| **M5** | Does redacted text still work? | **done** — 0.7 points of utility lost |
| **M6** | Ablations, docs, one command | **done**, with the caveats above |

M0 carried a stop condition: if the CFPB scrubbing had proved too inconsistent to
serve as labels, the project would have stopped and reported that. It was not
treated as a formality.

`make repro` regenerates every number above. A number it does not touch is a
number that does not belong here.
