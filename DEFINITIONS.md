# Definitions

**Locked: 2026-08-06, at the end of M0, before any measurement of any method.**

This document fixes what the three words in this project's claim mean: *personal information*,
*correct removal*, and *re-identification*. It is dated and does not change after M1 starts
without a written reason recorded in [`DECISIONS/`](DECISIONS/).

The reason for locking it before measuring is narrow and specific: every one of these
definitions can be adjusted after the fact in a direction that flatters the result. Fixing them
first is what makes the numbers mean anything.

The category list below was **built from the corpus, not invented**. It comes from hand
inspection of 100 narratives and context mining of 123,416 marker spans, both described in
[docs/02-data.md](docs/02-data.md). Categories nobody found in credit-card complaints are not
listed, however standard they are elsewhere.

---

## 1. What counts as personal information

Airlock uses three tiers. The distinction between them is the whole argument of the project, so
it is drawn carefully.

### Tier 1 — Direct identifiers

Information that identifies a person on its own, with no other data required.

| category | example from the corpus | has a pattern? |
|---|---|---|
| `PERSON` | a customer, relative, or named bank agent | no |
| `ACCOUNT_ID` | card or account number, `ending in XXXX` | yes |
| `GOV_ID` | SSN, driver's licence, passport | yes |
| `CONTACT` | phone number, email address, postal address | yes |
| `CASE_REF` | complaint or case reference, `case # XXXX` | yes |

Presidio and regular expressions handle most of this tier well. **Airlock is not trying to win
here**, and the rows where it loses are published anyway.

### Tier 2 — Contextual identifiers

Information that identifies a person only through the meaning of the surrounding sentence.
There is no pattern to match. This is where a model earns its place.

| category | example from the corpus |
|---|---|
| `RELATIONSHIP` | "my ex-husband", "my daughter in California", "my mother's maiden name" |
| `LOCATION_FINE` | "the Fremont branch", "my local police department", a street |
| `EMPLOYER` | "I had to retire from my job at…" |
| `LIFE_EVENT` | "after her second marriage", "when I was discharged" |
| `PROTECTED_ATTR` | race, age, disability status — the corpus contains "I'm a XXXX XXXX XXXX man" and "my total and permanent XXXX status with the VA" |
| `HEALTH` | the medical or veterinary procedure a Care Credit account was opened for |
| `ORG_THIRD_PARTY` | a named merchant or bank other than the one complained about |

`PROTECTED_ATTR` and `HEALTH` are in scope because the CFPB's own human redactors removed them,
and because they narrow a population sharply even when they identify nobody alone.

### Tier 3 — Quasi-identifiers

Information that is **not** personal information under any standard definition, and which still
identifies a customer to anyone holding the bank's transaction records.

| category | example | redacted by CFPB? |
|---|---|---|
| `AMOUNT` | `{$4.17}` — an exact transaction amount | **No.** Reformatted and kept, in 44.2% of narratives |
| `DATE` | `XX/XX/XXXX` | Yes, to month/day precision |
| `MERCHANT` | "I bought coffee on Main Street" | Inconsistently |
| `TEMPORAL` | "on Tuesday", "at 9am" | No |

**This tier is the contribution.** A sentence containing only Tier 3 information passes every
PII detector and can still pick one customer out of a database. The M4 attack exists to measure
exactly that, and Tier 3 is why the headline metric is re-identification rate and not span F1.

### Explicitly not personal information

Fixed here because the CFPB oracle marks these anyway, and any metric must handle the
disagreement rather than inherit it (see
[decision 002](DECISIONS/002-scoring-against-a-noisy-oracle.md)):

- Plain counts — "all three bureaus", "30 days late", "700 points"
- Interest rates and percentages
- Credit scores
- Legal and regulatory citations — "12 CFR 1026"
- Product and device models — "MacBook Pro"
- The company the complaint is filed against, which is a structured field of the record
- Ordinary words the redactor removed in error — the corpus contains the word *may* replaced
  with `XXXX` inside a quoted regulation

---

## 2. What counts as a correct removal

### Spans, not tokens

A **span** is a contiguous character range in the narrative. All measurement is at span level.

**Adjacent-marker merge rule.** Consecutive `XXXX` markers separated only by whitespace are one
span, not several. The CFPB redacts word by word, so a single street address becomes
`XXXX XXXX XXXX XXXX`; counting that as four correct detections would inflate any score roughly
fourfold. M0 measured a median longest run of 3 and a p95 of 8, so this is not a marginal
correction.

Markers joined by `/` are also one span, because that is how dates are written: `XX/XX/XXXX` is
one `DATE`, not three redactions.

### When a predicted span is correct

A predicted span **matches** a true span when the two overlap by at least one character *and*
neither extends more than 50% of the true span's length beyond it.

Three consequences, all intended:

- **Partial credit exists.** Catching "Fremont" out of "the Fremont branch" counts. The customer
  is protected either way, and an all-or-nothing rule would score identical protection as failure.
- **Over-broad predictions do not count.** Redacting a whole paragraph to be safe fails the
  50% condition. Otherwise redacting everything scores perfect recall.
- **One true span can be matched at most once.** Predicting five overlapping spans over one name
  is one match, not five.

### Recall, precision, and which oracle supplies which

| metric | definition | oracle |
|---|---|---|
| **Recall** | matched true spans ÷ all true spans | CFPB `XXXX` markers — noisy, see below |
| **Precision** | matched predicted spans ÷ all predicted spans | Injection (M2) — exact, because we wrote it |

Recall and precision come from **different oracles on purpose**. The markers say where PII was
but not what, and cannot say whether something they left alone was safe — so they cannot carry
precision. Injected PII has positions we recorded, so it can.

**Recall against raw markers is a lower bound, not an estimate.** Per
[decision 002](DECISIONS/002-scoring-against-a-noisy-oracle.md), four scoring conventions are
computed and ranked against a hand-labelled gold set. Every recall figure in this repository
names which convention produced it.

### Category-level correctness

The CFPB oracle cannot support category-level scoring, because the original text is gone and
`XXXX` does not say what it was. Therefore:

- **Category accuracy is measured on injected spans only**, where the category is known.
- Any category breakdown derived from marker context is labelled an **estimate** at every
  appearance.

---

## 3. What counts as a re-identification

Per [decision 001](DECISIONS/001-what-counts-as-re-identification.md), all three definitions are
computed and reported. They are nested: U ⊆ K ⊆ R.

The attacker holds the synthetic transaction database and one redacted narrative, extracts
whatever survived, and queries.

| | name | a narrative is re-identified when | role |
|---|---|---|---|
| **U** | **Unique match** | the query returns exactly one customer and it is the correct one | **headline** |
| **K** | **Small set** | the correct customer is in a returned set of size < 5 | reported |
| **R** | **Rank-1** | all customers are scored and the correct one ranks first | reported |

**U is the headline** because it is the most conservative — it yields the smallest
re-identification rate and so makes the weakest claim about risk.

**Re-identification rate** = re-identified narratives ÷ narratives attacked. Reported separately
for raw text, Presidio-redacted text, and Airlock-redacted text, under each of U, K and R.

A narrative counts as attacked whether or not the attacker returns anything. Narratives where
the attack finds nothing are successes for the redactor and stay in the denominator.

### What is not a re-identification

- Returning a set containing the correct customer that is large enough to fail both U and K.
- Matching a customer who is not the correct one. This is an attacker error, scored as a
  non-re-identification, and its rate is reported as the attack's false-positive rate — an
  attacker who guesses constantly is not a good attacker.

---

## 4. Terms used elsewhere in this repository

- **Narrative** — the free text a consumer wrote, in the `Consumer complaint narrative` column.
- **Marker** — a run of two or more capital X's in published CFPB text, standing where a human
  removed something.
- **Oracle** — a source of truth about where PII is. This project has two: markers (noisy,
  recall) and injection (exact, precision).
- **Injection** — inserting generated personal information into an already-scrubbed narrative at
  positions we record, to obtain exact labels.
- **Linkage attack** — attempting to find the one customer in a database that a redacted
  narrative refers to.
- **Frontier model** — a large hosted model (Claude, GPT). It appears in exactly one place in
  this project: M5, answering questions about redacted text.

---

## Amendments

None. Any change is appended here with its date and its reason, and the reason has to say what
was learned that the original definition could not accommodate.
