# What the existing free tools already achieve

**Status: M1 complete. Every number here comes from `make m1`.**

The brief requires this table be published *before* the thing that beats it is built. This is
the number to beat, committed in advance.

---

## The setup

Three baselines, over a seeded sample of **15,000 marked narratives** containing **119,261**
marker spans (after the adjacent-merge rule in [DEFINITIONS.md](../DEFINITIONS.md)):

| baseline | what it is |
|---|---|
| `presidio` | [Microsoft Presidio](https://microsoft.github.io/presidio/), the standard open-source PII detector |
| `spacy` | spaCy `en_core_web_lg` named-entity recognition on its own, no Presidio wrapper |
| `regex` | Plain patterns — SSN, card number, email, phone, URL, street address, ZIP. No model. |

Recall is scored against the CFPB `XXXX` markers.

---

## Read this before quoting any number below

The published text **does not contain personal information**. It contains `XXXX` where the
personal information used to be. Every detector here is working from surrounding context with no
surface form to read — the name is gone.

So these are a **floor**, understated by an unmeasured amount, and comparable to each other only
on this substrate. They are **not** "what Presidio achieves in production", and nothing in this
repository quotes them that way.

---

## Results

| method | recall | found / total | predictions made | seconds |
|---|---:|---:|---:|---:|
| **spacy** | **69.5%** | 82,861 / 119,261 | 173,603 | 467 |
| **presidio** | **61.6%** | 73,487 / 119,261 | 113,163 | 674 |
| **regex** | **0.0%** | 0 / 119,261 | 1,434 | 4 |

### By estimated category

Categories are **inferred from surviving context**, not known — the oracle cannot supply true
categories because the original text is gone. `NOT_PII_ESTIMATED` marks spans that context says
were counts or rates, **where a low score is correct behaviour, not a miss.**

| category | spans | regex | spacy | presidio |
|---|---:|---:|---:|---:|
| UNKNOWN | 72,010 | 0.0% | 62.6% | 56.3% |
| DATE | 27,918 | 0.0% | 88.3% | 75.7% |
| ORG_OR_PERSON | 9,986 | 0.0% | 85.2% | 79.4% |
| AMOUNT_OR_COUNT | 3,816 | 0.0% | 43.1% | 37.8% |
| *NOT_PII_ESTIMATED* | *2,425* | *0.0%* | *45.6%* | *25.6%* |
| ACCOUNT_ID | 1,652 | 0.0% | 61.7% | 56.2% |
| PERSON | 690 | 0.0% | 92.9% | 91.9% |
| CASE_REF | 610 | 0.0% | 22.6% | 21.1% |
| CONTACT | 134 | 0.0% | 64.9% | 64.9% |
| LOCATION | 20 | 0.0% | 80.0% | 70.0% |

---

## Three findings, in order of importance

### 1. The regex row is 0.0% *by construction*, and that invalidates this substrate for pattern methods

This is not a bug and not a failure of regular expressions. It was verified directly:

```
regex predictions: 1,434 | overlapping any marker: 0

Can a regex ever match a marker? Markers are runs of the letter X.
  SSN     matches "XXXX"? False      CARD  matches "XXXX"? False
  EMAIL   matches "XXXX"? False      PHONE matches "XXXX"? False
  ZIP     matches "XXXX"? False      URL   matches "XXXX"? False
```

A credit card number regex looks for **digits**. A marker is **letters**. No pattern in the set
can match a marker, at any position, ever. The score is structurally pinned to zero.

**What this means:** the `XXXX`-marker oracle cannot evaluate pattern-based detection *at all*.
It can only measure detection that works from context — which is a real and interesting
capability, and happens to be exactly the capability Airlock is being built for, but it is not
the whole task.

The brief anticipated that Presidio would win the structured-PII row and said publishing that
row was the point. **The actual result is stranger: on this substrate the structured-PII row
cannot be scored for anyone.** That row has to come from injection (M2), where a card number is
an actual card number.

### 2. spaCy alone beats Presidio, which wraps it

69.5% against 61.6%, on identical input. Presidio also made **35% fewer predictions** (113,163
against 173,603).

Presidio is spaCy plus pattern recognizers plus filtering. The pattern recognizers cannot fire
here, for the reason above. So what is left is spaCy with Presidio's filtering applied on top —
and that filtering is discarding true positives on this substrate.

Look at the `NOT_PII_ESTIMATED` row, though: **Presidio 25.6% against spaCy 45.6%**, and lower is
better there. Presidio's conservatism is doing real work — it is markedly better at declining to
flag the spans that context says were plain counts and rates.

So the honest reading is not "spaCy is better". It is that the two sit at different points on
the same trade-off, and a single recall number hides that. Both go in the comparison table.

### 3. Structured PII survives human redaction, in small numbers

Running the regex baseline over already-scrubbed text found 1,434 pattern matches:

| pattern | matches in 15,000 scrubbed narratives |
|---|---:|
| ZIP-shaped | 1,429 |
| Email | 2 |
| Street address | 2 |
| Phone | 1 |

**The ZIP figure is not a leak count.** That pattern matches any five-digit number, and
complaint text is full of them — dollar amounts written without the CFPB's brace formatting,
account fragments, reference numbers. The true ZIP leak count is far lower and this baseline
cannot separate them.

The email, address and phone matches are more likely to be genuine — five confirmed-shape direct
identifiers that a trained human redactor missed. Five in fifteen thousand is a low rate. It is
not zero, and the CFPB's process is a careful one.

---

## What M1 changes about the plan

1. **The definitive baseline comparison moves to injected data.** Not because these numbers are
   wrong, but because this substrate cannot score a whole class of method. M2 re-runs all three
   baselines on injected narratives where every category has a realistic surface form.
2. **These numbers stand as the contextual-detection floor.** They remain the answer to "how well
   do the free tools do when the only signal is context", which is the regime Airlock targets.
3. **The model cannot be trained on this text.** A model fitted to predict marker positions in
   text containing `XXXX` learns `XXXX → redact`, scores near-perfect, and is worthless on real
   text where no such token exists. Injection is therefore the only viable training substrate,
   which promotes M2 from "supplies precision" to load-bearing for the entire model.

---

## Reproducing this

```bash
make m1
```

| script | produces |
|---|---|
| `scripts/m1_smoke_test.py` | exploratory check, prints only, publishes nothing |
| `scripts/m1_baselines.py` | `results/m1_baselines.csv`, `results/m1_baselines.txt` |

Sample seed `20260806`, 15,000 narratives. Runtime about 19 minutes on an M1 MacBook, no GPU,
dominated by Presidio at 674 seconds and spaCy at 467.
