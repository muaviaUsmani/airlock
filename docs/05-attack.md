# How re-identification is measured

**Status: the attack runs. Raw and regex rows are final; Presidio, spaCy and Airlock follow.
The Airlock row waits on M3.**

---

## Why this document exists

Every redaction tool claims it removed the personal information. The claim is almost never
tested, because testing it means trying to undo it.

Airlock's headline number is not "how many names did we find". It is **can the customer still be
identified from what is left**. Answering that requires an attacker, so this project builds one.

---

## The attacker's database

A deliberately minimal synthetic card system. It is **not a data generator** — its only purpose
is to answer *given this redacted narrative, can I find exactly one customer?*

**No real data, ever.** Every value is generated from word lists in
[`scripts/m2_transactions.py`](../scripts/m2_transactions.py) with seed `20260806`.

| table | rows | fields |
|---|---:|---|
| customers | 10,000 | name, address, city, state, zip, phone, email, employer, a relative, a health procedure, a life event |
| cards | 11,825 | last 4, opened date |
| merchants | 400 | name, category, city |
| transactions | 359,375 | amount, date, merchant, card |

Four tables. No balances, no payments, no statements, no authorisation flow, no fraud model.
The brief is explicit that every hour spent making this realistic is an hour stolen from the
work that matters, and that if it starts growing features, focus has drifted.

---

## The finding that justifies the whole project

Before any attack runs, the database already shows why "did we remove the names?" is the wrong
question. **How identifying is each field on its own?**

| field | unique | mean customers per value |
|---|---:|---:|
| phone | 100.0% | 1.0 |
| full name | 85.4% | 1.2 |
| card last 4 | 52.0% | 1.7 |
| transaction amount | 30.7% | 16.3 |
| city | 0.0% | 333.3 |
| zip | 0.0% | 333.3 |
| employer | 0.0% | 2500.0 |
| transaction date | 0.0% | 478.7 |
| merchant name | 0.0% | 1328.8 |
| **amount + date** | **96.0%** | **1.0** |
| **amount + date + merchant** | **99.7%** | **1.0** |

Read the last two rows against the middle of the table. An exact **date** identifies nobody —
479 customers share any given day. A **merchant** identifies nobody — 1,329 customers shop at
any given store. An **amount** alone narrows to 16 people.

Put the three together and you have **99.7% uniqueness**.

**None of those three fields is personal information under any standard definition.** No PII
detector removes them. Presidio does not flag `$47.13`, or `Tuesday`, or `Corner Coffee`. And
M0 measured that the CFPB's own human redactors leave an intact dollar amount in **44.2%** of
published narratives.

That is the gap this project exists to measure, and it is why the headline metric is
re-identification rate rather than span-level F1. A redactor can score perfectly on every name
in the corpus and still leave every customer identifiable.

### An honest caveat about that number

96% and 99.7% are properties of **this database at this size**. Uniqueness falls as the customer
population grows — 10,000 customers is a choice, and in a bank with ten million the same
quasi-identifiers would narrow less sharply.

So the re-identification rates reported at M4 are **conditioned on database size**, and
population size is carried as an ablation axis at M6 rather than left as an unstated assumption.

---

## What counts as a re-identification

Settled in [decision 001](../DECISIONS/001-what-counts-as-re-identification.md). All three
definitions are computed from one attack run; they are nested, U ⊆ K ⊆ R.

| | name | re-identified when | role |
|---|---|---|---|
| **U** | Unique match | the query returns exactly one customer and it is the correct one | **headline** |
| **K** | Small set | the correct customer is in a returned set of size < 5 | reported |
| **R** | Rank-1 | all customers are scored and the correct one ranks first | reported |

**U is the headline** because it is the most conservative — it produces the smallest
re-identification rate, and therefore the weakest claim about risk.

The three are not ranked by accuracy, because there is no ground truth about what
re-identification "really" means. They are three definitions of a phenomenon, not three
predictors of a fact. What *is* measured is their **discriminative power** (how sharply each
separates the redaction methods) and their **stability** (how much each moves when the
attacker's thresholds are perturbed).

---

## What the attack will be run against

Per [decision 004](../DECISIONS/004-two-injection-distributions.md) the headline comes from a
natural-frequency set, and per
[decision 007](../DECISIONS/007-tier3-frequencies-cannot-come-from-markers.md) that set is
**`natural_v2`** — 4,000 narratives, each carrying personal information drawn from one synthetic
customer's real record. `natural` is still built and still reported, as the under-estimate it
turned out to be.

A sanity check on that linkage, using an exact join on amount and date alone and nothing else:

```
injected narratives:                    4,000
  linked transaction resolves to 1 customer:  3,653  (91.3%)
  correct customer preserved:                          100.0%
```

That is a **construction check, not the attack** — it confirms the M2 chain holds end to end.
The real attack has to extract those values from redacted prose rather than being handed them.

---

## First result: the distribution decides the headline

Before the model exists, the attack already produced its most important number — and it is about
measurement, not redaction.

The attack was run twice on identical narratives with an identical attacker. The only difference
was where the tier 3 injection frequencies came from.

| injected set | tier 3 frequencies from | raw-text U |
|---|---|---:|
| `natural` | the CFPB `XXXX` markers | **8.6%** |
| `natural_v2` | counted from surviving text | **36.9%** |

**A 4.3x difference, from a choice that looks like bookkeeping.**

The cause is [decision 007](../DECISIONS/007-tier3-frequencies-cannot-come-from-markers.md).
Markers record what the CFPB *redacted*. Tier 3 is by definition what it *does not* redact — so
asking the marker oracle how often complaints mention money returns 2.5%, when counting the text
directly returns **44.2%**. The oracle is not wrong; it faithfully reports that money is almost
never redacted. It was asked a question it cannot answer.

`natural` is kept and published rather than corrected away, because it is what following the
brief's instruction literally produces. **An oracle built from redaction decisions cannot tell
you about the things nobody redacted**, and a headline built on one is several times too small.

### What the numbers look like so far

At the pre-registered configuration, on `natural_v2`:

| method | U unique | K set<5 | R rank-1 | attacker FP |
|---|---:|---:|---:|---:|
| raw | 36.9% | 44.3% | 37.0% | 0.5% |
| regex | 25.7% | 32.7% | 26.0% | 0.1% |

Read the regex row carefully. A pattern-based redactor — which strips card numbers, emails,
phones, addresses and dollar amounts — removes only about **a third** of the re-identification
risk. Two thirds of the customers remain findable from what a regular expression considers
harmless.

Presidio, spaCy and Airlock rows follow. The encoder row is pending M3.

---

## How the adversary matches

Settled in [decision 005](../DECISIONS/005-how-the-adversary-matches.md), which resolved the
brief's open fork #3. The framing that did the work:

> **Exact matching is fuzzy matching with zero tolerance.**

Exact and fuzzy are not two attackers. An attacker is described entirely by *which fields it
uses* and *how much slack it allows*, so this is one function of two arguments and M4 sweeps
both. Reporting "exact gets A%, fuzzy gets B%" invites the question *B% at what tolerance?* and
has no answer; a sweep answers it and costs barely more to run.

| axis | swept over |
|---|---|
| fields | amount · amount+date · +merchant · +city |
| tolerance | exact · ±1 · ±3 · ±7 days, and ±$0 · ±$1 · ±$5 · ±$25 |

Query order follows **measured** selectivity rather than convenience: an amount (16.3 customers
per value) or a merchant can open a search; a date (479 per value) can only narrow one. An
attacker holding nothing but a date has identified nobody, and the matcher returning nothing
there is the correct answer rather than a shortcut.

### The safeguard, which matters more than the sweep

A tolerance sweep is an obvious way to manufacture a headline: loosen until Presidio-redacted
text leaks a lot, tighten until Airlock-redacted text leaks little, report the gap.

So the selection rule was **pre-registered in decision 005 before any attack code was written**:

1. Tolerance and field set are chosen on **raw text only** — the condition where no redaction
   method is involved and none can be favoured.
2. Selection maximises unique re-identification subject to the attacker's false-positive rate
   staying under 5%.
3. That one configuration is applied **unchanged** to every method.
4. The full sweep is published anyway, so the headline can be located on the surface rather than
   taken on trust.
5. If the ranking of methods changes across the sweep, that is a finding about instability and
   goes in the README — not a reason to hunt for a configuration where it does not.

Point 1 is load-bearing: tuning the attacker against nobody's redaction is what makes the
comparison it then performs neither rigged for nor against any method.

### Why the attacker's error rate is always quoted beside its success rate

A re-identification rate without a false-positive rate is meaningless — an attacker that guesses
constantly will "identify" plenty of people. `DEFINITIONS.md` requires both, and matching the
wrong customer is scored as a non-re-identification and reported separately.
