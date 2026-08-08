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
