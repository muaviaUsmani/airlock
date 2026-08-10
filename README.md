# Airlock

**A 372MB model, running on a laptop, that strips personal information out of bank complaint
text — and an attack that measures whether the customer can still be identified afterwards.**

---

## TL;DR

A bank has hundreds of thousands of written customer complaints. It wants a frontier model to
analyse them. It cannot send them, because the text is full of personal information that is not
allowed to leave the building.

So something has to strip that information out first — and that something has to run **inside
the company's own trust boundary**, because *if you could send the text out to be checked, you
would not have needed to check it.*

"Inside the boundary" means infrastructure the company controls: its own VPC, its own cloud
account, under its own contracts. It does **not** mean a laptop
([decision 012](DECISIONS/012-the-premise-is-a-trust-boundary-not-a-laptop.md)). Airlock is
measured on an M1 because that is a useful floor to know and a good demo, not because a laptop is
what protects the data.

Airlock is that something. It is a small model that runs wherever the company's boundary is —
and small enough that inference on an M1 MacBook with no GPU is measured here as the floor.

*Training* uses a rented GPU (~$0.15 an hour, about 70 minutes for every run in this project).
That does not weaken the privacy argument: the training data is public CFPB text with synthetic
personal information we generated ourselves, so nothing confidential goes anywhere. Only the
deployed model has to stay local. See
[decision 011](DECISIONS/011-training-moves-to-rented-gpu.md).

The interesting part is not the redaction. It is the **measurement**. Anyone can claim they
removed the personal information. Airlock builds a synthetic transaction database and then
*attacks its own output* — taking the redacted text and trying to find the one customer it
belongs to. That attack is the headline result.

> **Status: M0–M4 complete. M5 blocked on an API key; M6 partly done.** The corpus is characterised and
> [DEFINITIONS.md](DEFINITIONS.md) is locked. The three headline numbers below are the *shape*
> of the claim, not the claim — they are filled in only when a committed script produces them,
> per [the constitution](.specify/memory/constitution.md). Numbers that cannot be regenerated do
> not get published here.
>
> **What M0 already found, before any model exists:** the CFPB's human redactors leave an intact
> dollar amount in **44.2%** of narratives. An exact transaction amount is one of the strongest
> join keys there is against a transaction database. The text has been scrubbed to a published
> standard by a trained person, and it still carries the field an attacker would most want —
> which is the entire argument for measuring re-identification rather than counting names.
> Details in [docs/02-data.md](docs/02-data.md).
>
> **And what M1 found:** scored against the CFPB markers, spaCy gets 69.5% and Presidio 61.6% —
> but plain regex scores **0.0%, structurally**. A card-number pattern looks for digits; a
> redaction marker is letters. No pattern can ever match one. The free labels cannot evaluate
> pattern-based detection at all, which is why the like-for-like comparison has to happen on
> injected data. Details in [docs/03-baselines.md](docs/03-baselines.md).
>
> **What M3 found:** on real prose the encoder reaches **F1 81.8% against Presidio's 62.9%**,
> driven by precision (97.5% vs 52.8%) — but **Presidio still finds more** (77.9% recall vs
> 70.5%). Rebuilding the injector to use carriers mined from the corpus rather than sentences we
> wrote moved `ORG_THIRD_PARTY` from **0.1% to 45.0%**, and collapsed seed-to-seed variance from
> ±17.1 to ±1.0. The one well-powered category that got no real carriers, `TEMPORAL`, is also
> the only one that did not improve — which is as close to a controlled experiment as this
> project has managed. Details in [docs/04-model.md](docs/04-model.md).
>
> **And the result that surprised us most:** running the same attack on the same narratives with
> the same attacker, and changing only where the injection frequencies came from, moved the
> re-identification rate from **8.6% to 36.9%**. Frequencies derived from the CFPB's redaction
> markers say complaints mention money 2.5% of the time; counting the text says **44.2%**. The
> markers only record what was *removed*, and the fields that enable re-identification are
> precisely the ones nobody removes. Details in
> [docs/05-attack.md](docs/05-attack.md).
>
> **And what M2 found:** in the synthetic transaction database, an exact date identifies nobody
> (479 customers share one) and a merchant identifies nobody (1,329 do). Put an amount, a date
> and a merchant together and you reach **99.7% uniqueness**. None of the three is personal
> information; no PII detector removes any of them. Details in
> [docs/05-attack.md](docs/05-attack.md).

---

## Mistakes we found in our own method

This section is near the top on purpose. Every item below was caught by attacking our own
results rather than by anything breaking, and **most of them produced plausible numbers, not
errors** — which is exactly why they are dangerous and why they are listed before the findings
they affect.

> **[docs/09-lessons.md](docs/09-lessons.md) is the plain-English version of this**, written for
> someone who does not want the tables — what went wrong, in ordinary words, and what we would
> tell someone starting a similar project. This project was a learning exercise; that page is the
> part that transfers.

### 1. Our training recipe, not model size, explains the headline (confirmed, 2026-08-09)

M3 reports a 70.7M encoder beating a 434M one by ~5 F1, and we nearly published that as a
finding about model size. **It is a finding about our own recipe.**
`scripts/m3_train_encoder.py` uses **one learning rate (3e-5) for all three model scales**, a
**fixed 3 epochs**, and has **no validation split, no early stopping and no best-checkpoint
selection** — it keeps whatever the last epoch produced. The training losses show the cost:

| arm | epoch 1 | epoch 2 | epoch 3 |
|---|---:|---:|---:|
| micro 70.7M | 0.3684 | 0.0095 | **0.0053** |
| base2 184M | 0.1240 | 0.0012 | **0.0005** |
| large 434M | 0.0711 | 0.0006 | **0.0003** |

`large` had fitted the training set by epoch 2 and then trained a third epoch anyway, while
`micro` was the only arm still learning when the schedule ended. **Each arm was therefore scored
at a different point on its own overfitting curve**, and the more capacity a model has, the
further past its optimum we stopped.

Retraining all three for **one** epoch, changing nothing else, **inverts the ranking**
([m6_epoch_ablation](results/m6_epoch_ablation.txt)):

| arm | 1 epoch | 3 epochs | delta |
|---|---:|---:|---:|
| micro | 83.8 | **85.5** | −1.8 |
| base2 | 82.1 | 77.4 | +4.7 |
| large | **84.7** | 78.0 | +6.7 |

Micro is the only arm that *wants* three epochs. The same cause shows up on a second axis: with
epochs fixed, more data means more steps means deeper over-training, and both larger arms get
**worse** from 2k to 15k rows while micro improves
([m6_data_scaling](results/m6_data_scaling.txt)) — which also disposes of the competing
"15,000 examples starve a 434M model" hypothesis, since starvation predicts the opposite.

The honest phrasing of the M3 headline is therefore *"under a single training recipe applied
unchanged across three scales, the larger models overfit and lose"* — a statement about the
experiment, not about capacity. **One epoch is not the fix either**; it is a second arbitrary
stopping point. A real size comparison needs a validation split, per-arm early stopping, and a
learning rate chosen per scale (currently a module constant, not even an argument). See
[decision 017](DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md).

### 2. Unmeasured methods printed as hard zeros (found, not yet fixed)

`m3_arms.txt`'s per-category table shows `0.0%` for Presidio and spaCy across all 16 categories.
They were never run — the eval was invoked with `--no-baselines`. A method that was not measured
must render as "not run", never as a number a reader can quote.

### 3. "Inference cost on the M1" was measured on a rented GPU (found, not yet fixed)

The same report prints `model on disk 0 MB` and `peak process memory 7 MB` under a heading that
[decision 011](DECISIONS/011-training-moves-to-rented-gpu.md) requires to be measured on the M1.
It ran on the GPU box and the size lookup failed. Both numbers are false.

### 4. M5 scored models against answer keys they could not match — three ways

**(a) Blank answers graded as wrong (fixed).** 8.4% of the corpus has no CFPB `Sub-product`.
`str(nan)` is `"nan"`, so those rows were scored as misses no reader could avoid — **and `"nan"`
was offered to the grader as a valid multiple-choice option on every row**. Rows with no answer
key are now excluded from that question's denominator.

**(b) A multiple-choice list missing most of the right answers (fixed).**
`options["issue"] = sorted({...})[:12]` took the first twelve values **alphabetically** out of 27.
Only **32.6% of the true answers were among the options offered** — the two most common correct
answers were excluded because they begin with "P" and "O". That capped the question at 32.6%
before the reader saw any text; it scored 12.9%. All labels present in the graded slice are now
offered, and the script asserts the invariant that a correct answer is always reachable, printing
the achievable ceiling when it is not.

**(c) A question whose answer is never in the text (documented, kept).** "Did the company give
money back?" is recorded *after* the complaint is filed. The reader correctly answers UNKNOWN and
is scored wrong.

Every question is now published against its majority-class baseline, which immediately shows that
two of the three sit *below* the score you get by ignoring the text entirely.
See [decision 014](DECISIONS/014-m5-answer-key-and-baselines.md).

### 5. The writer arm's cost was inflated ~9× by our own padding waste (fixed)

Generation batched narratives in arrival order, and a batch runs until its *longest* member
finishes, so short narratives paid for long ones: 11,400 ms/narrative. Sorting by length before
batching — changing no output — brought it to 1,250 ms. Any "generative costs N× more" claim made
before that fix was measuring our implementation, not the architecture. HANDOFF §5 had already
flagged the same disease in the writer's *training* cost; it was present on the inference side too.

### 6. Two claims in our own handoff did not survive checking

The handoff stated that M5's `relief` question "scored 0% even on raw text". The committed smoke
output records **75.0%** — the highest of the three questions. It also stated the writer's drift
measurement was "built and unit-tested"; there were **no tests** for it in the repository. There
are now (`scripts/test_m3_predict_generative.py`). A handoff is the document a later reader
trusts without re-deriving, which makes an unverified claim in one more costly than usual.

---

## Getting the models and data

Everything is published read-only, and **no AWS account is needed** — these send
no credentials:

```bash
scripts/fetch_weights.sh repro     # models + synthetic data (7.5 GiB) — what make repro needs
scripts/fetch_weights.sh corpus    # the pinned CFPB snapshot (8.4 GiB), verified against its sha256
scripts/fetch_weights.sh all       # everything (15.9 GiB)
```

Or directly:

```bash
aws s3 sync s3://airlock-redaction/m3/models models --no-sign-request
curl -O https://airlock-redaction.s3.amazonaws.com/results/m5_utility.txt
```

| prefix | size | what it is |
|---|---:|---|
| `m3/models/` | 7.3 GiB | the ten trained arms — micro ×3, base2 ×3, large ×3, writer |
| `data/synthetic/` | 85 MiB | the injected sets the models were trained and evaluated on |
| `data/interim/` | 138 MiB | filtered credit-card narratives |
| `data/raw/` | 8.4 GiB | the pinned CFPB snapshot and its `PROVENANCE.txt` |
| `results/` | 305 KiB | every results file and run log |

**The corpus is the only artifact here that cannot be regenerated.** Its source
URL is a rolling snapshot with no versioning, so the 2026-08-06 bytes every
number was computed from vanish whenever the CFPB republishes. That is why it is
mirrored with a sha256, and why `fetch_weights.sh` checks it.
See [decision 018](DECISIONS/018-publishing-the-weights.md).

---

## The claim this project is trying to earn

> On real credit-card complaint narratives, a **372MB** model running on a laptop removes
> **36.3 percentage points** more personal information than Microsoft Presidio, and reduces the
> rate at which a customer can be re-identified from the remaining text from **36.9%** to
> **0.2%** — while destroying **one fifth** as much non-personal text as Presidio and one ninth
> as much as spaCy.
>
> *(The utility half — how many business questions a frontier model still answers correctly —
> is M5 and is not yet run; it needs an API key. `collateral` stands in for it meanwhile.)*
>
> **The honest asterisk:** the two ways of measuring "removes more PII" disagree. Airlock removes
> 83.0% of PII characters against Presidio's 46.7% on injected text, but Presidio has higher
> *span* recall on real prose, 77.9% against 70.5%. Both are published; see
> [docs/05-attack.md](docs/05-attack.md).

Three numbers. All mechanically measurable. None requires a human or a model to judge anything.

**If any of the three cannot be measured honestly, this README reports that instead.** A clean
negative result is an acceptable outcome here and gets written up as one — see
[docs/08-limitations.md](docs/08-limitations.md).

---

## Why this needs a model at all

Some personal information is easy. A credit card number is sixteen digits and passes a
checksum. An email address has an `@`. A regular expression finds these perfectly, and
[Microsoft Presidio](https://microsoft.github.io/presidio/) already does it well and for free.

**Airlock is not trying to beat Presidio at that, and does not pretend to.**

The hard part is the information that has no pattern:

> *"I explained to the manager at the Fremont branch that my mother's maiden name had changed
> after her second marriage, and he still wouldn't unlock the card my ex-husband opened in
> 2019."*

There is no regular expression for *"my mother's maiden name"*, *"the Fremont branch"*, or
*"my ex-husband"*. Every one of them helps identify the customer. That is where a model earns
its place.

### And then the part that is the actual contribution

Even after you remove every name and number, the text can still identify someone:

> *"I bought coffee on Main Street on Tuesday for $4.17 and the card declined."*

That sentence contains no personal information by any standard definition. It also uniquely
identifies one customer, if you happen to hold the bank's transaction records.

So the real question is not *"did we find all the names?"* It is **"can the customer still be
identified after we're done?"** Answering that means actually trying to identify them — which
is what the synthetic transaction system in this project is for.

---

## How it works

```
  CFPB complaints          the XXXX markers left behind by CFPB staff
  (real text, public)  ──▶ are free labels: a human decided personal
                           information was here.  →  RECALL oracle

  clean narratives     ──▶ inject personal information we generated
  (no markers)             ourselves, at positions we recorded
                                                   →  PRECISION oracle

  redacted text        ──▶ synthetic transaction DB tries to find the
                           one matching customer
                                                   →  THE HEADLINE
```

Three sources of truth, none of which is a human or a model grading an answer.

| piece | what it is | where |
|---|---|---|
| **Corpus** | Real consumer complaints, published by the US CFPB, already scrubbed by humans | [docs/02-data.md](docs/02-data.md) |
| **Recall oracle** | The `XXXX` markers CFPB staff left behind. Noisy — the noise is measured, not assumed away | [docs/02-data.md](docs/02-data.md) |
| **Precision oracle** | Personal information we injected ourselves, at positions we wrote down | [docs/02-data.md](docs/02-data.md) |
| **The adversary** | A deliberately minimal fake card system. Not a data generator — an attacker | [docs/05-attack.md](docs/05-attack.md) |

---

## Running it

```bash
./scripts/bootstrap.sh
```

That builds a virtual environment, downloads the CFPB corpus (~1.3GB compressed, ~8.4GB
unpacked) and records which nightly build you got. The corpus is **never committed** to this
repository — it is public data that is re-published every night, so what belongs in git is the
download step and a record of which night the numbers came from.

Then:

```bash
make repro
```

That regenerates every number in this README from scratch. A number `make repro` does not touch
is a number that does not belong here.

Prefer containers? Same thing, no Python version to match:

```bash
docker compose run --rm airlock make repro
```

Run `make help` to see the individual milestones.

---

## Documentation

Written as the work happens, not assembled at the end. Assume the reader remembers nothing —
including the person who wrote it.

| document | what is in it |
|---|---|
| [DEFINITIONS.md](DEFINITIONS.md) | What counts as personal information, a correct removal, a re-identification. **Locked at M0.** |
| [docs/01-why.md](docs/01-why.md) | The problem in plain language, with examples |
| [docs/02-data.md](docs/02-data.md) | Where the corpus comes from and what is wrong with it |
| [docs/03-baselines.md](docs/03-baselines.md) | What Presidio, spaCy and plain regex already achieve |
| [docs/04-model.md](docs/04-model.md) | What was trained, and why that architecture |
| [docs/05-attack.md](docs/05-attack.md) | How re-identification is measured |
| [docs/06-utility.md](docs/06-utility.md) | The leakage-versus-usefulness trade-off |
| [docs/07-ablations.md](docs/07-ablations.md) | What each component actually contributed |
| [docs/08-limitations.md](docs/08-limitations.md) | Everything this does not do. Written honestly. |

**Specs and plans** live in [`specs/`](specs/), one directory per milestone, managed with
[Spec Kit](https://github.com/github/spec-kit). Each has the feature spec, the implementation
plan, and the task breakdown. Start there if you want to know *why* something is built the way
it is rather than *what* it does.

**Decisions** live in [`DECISIONS/`](DECISIONS/) — one file per fork, with the options that were
considered and the reasoning attached. The brief this project was built from left three
decisions deliberately open; each one is resolved there, in writing, before the code that
depends on it was written.

The [project constitution](.specify/memory/constitution.md) holds the rules that do not bend:
reproducibility, no secrets, negative results get published, and forks get surfaced rather than
silently resolved.

---

## Milestones

| | milestone | done when | status |
|---|---|---|---|
| **M0** | Characterise the corpus | `DEFINITIONS.md` exists, corpus statistics committed | **done** |
| **M1** | Measure the baselines | Published table of what free tools already achieve | **done** |
| **M2** | Injection harness + adversary | N narratives with known PII positions, each mapped to one synthetic customer | not started |
| **M3** | The model | Beats M1 on contextual categories, or reports that it does not | not started |
| **M4** | **The attack** | Re-identification rate for raw / Presidio / Airlock text | not started |
| **M5** | Does redacted text still work? | Leakage-versus-utility chart | not started |
| **M6** | Ablations, docs, one command | Someone who has never seen this repo can clone it and get these numbers | not started |

M0 carries a stop condition: if the CFPB scrubbing turns out to be too inconsistent to serve as
labels, the project stops and reports that. It is not treated as a formality.

---

## What this is not

- **Not a general-purpose PII detector.** It is tuned to one domain. The narrowness is the
  argument, not a limitation to apologise for.
- **Not a compliance tool.** Nothing here satisfies any regulation, and nothing in this
  repository should be read as suggesting it does.
- **Not a replacement for Presidio.** The interesting result is where the two differ.
- **Not a product.** No interface beyond a command line. No hosting, no service.
- **Not a benchmark of frontier models.** A frontier model appears in exactly one place — M5,
  answering questions about redacted text.

---

## Context

Airlock is the first of four projects on one thesis: *a small open-weight model, trained for one
narrow job, running alongside a frontier model rather than replacing it.* The portfolio asks when
a small team should call Claude or GPT, and when they should run their own small model.

Airlock answers from the **privacy** angle: the task exists precisely because the data cannot
leave the building.
