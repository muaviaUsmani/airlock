# The corpus, and what is wrong with it

**Status: M0 complete for the corpus-characterisation half. Every number here comes from
`make m0`.**

---

## Where the text comes from

The US Consumer Financial Protection Bureau (CFPB) runs a public complaints database. When a
consumer complains about a financial company, the complaint is recorded, and — if the consumer
consents — the narrative they wrote in their own words is published.

It is a free bulk download, refreshed nightly, and it is real text written by real people about
real money problems. That last part matters: no synthetic corpus reproduces the way somebody
writes when they are angry at their bank at 1am.

| | |
|---|---|
| Source | `https://files.consumerfinance.gov/ccdb/complaints.csv.zip` |
| Downloaded | 2026-08-06 (the file is rebuilt nightly; ours is recorded in `data/raw/MANIFEST.txt`) |
| Size | 1.3GB compressed, 8.4GB as CSV |
| Rows | **16,935,987** complaints |
| With a written narrative | **3,831,109** (22.6%) |

### Narrowing to credit cards

The CFPB renamed its product categories partway through the corpus history, so credit-card
complaints live under two different labels. Both are kept. The newer label also contains things
that are not credit cards — prepaid, gift, payroll and government benefit cards — and those are
dropped, because a gift card complaint is a different domain with different personal information
in it.

| kept | narratives |
|---|---:|
| General-purpose credit card or charge card | 176,582 |
| Store credit card | 29,533 |
| (no sub-product recorded — older rows) | 18,837 |
| **total** | **224,952** |

Dropped as not-a-credit-card: 9,639.

**224,952 narratives.** The brief set a stop condition at roughly 20,000. We are nine times over
it, so the project proceeds.

---

## The free labels, and why they are only half free

Before publishing, CFPB staff remove anything that could identify the consumer and leave a run
of capital X's behind:

> *"I called XXXX on XX/XX/XXXX about my XXXX XXXX card ending in XXXX"*

Every one of those runs is a spot where a trained human, following a published standard, decided
personal information was present. That is a redaction oracle we did not have to pay for, on real
text, in exactly the right domain. It is the single reason this project is possible without a
labelling budget.

| | narratives | share |
|---|---:|---:|
| With at least one marker | 184,633 | 82.1% |
| With five or more markers | 129,849 | 57.7% |
| **With no marker at all** | **40,319** | **17.9%** |

That last row is not a leftover. Narratives with no markers are text a human has already
scrubbed clean, which makes them the raw material for M2: we inject personal information we
generated ourselves, at positions we write down, and get exact labels instead of noisy ones.

### How much text is gone

| | mean | p5 | median | p95 |
|---|---:|---:|---:|---:|
| Words per narrative | 216 | 27 | 160 | 591 |
| Markers per narrative | 12 | 0 | 6 | 42 |
| Markers as % of words | 5.3 | 0.0 | 3.8 | 15.5 |
| — among marked narratives only | 6.5 | 0.9 | 4.9 | 16.7 |

**The p5-to-p95 spread on marked narratives is 0.9% to 16.7% — a factor of eighteen.** This is
the inconsistency the brief warned about, and it is now measured rather than assumed. Some
narratives are scrubbed to near-unreadability; others are barely touched. A model that matches
the average will look wrong on both tails, and any recall number quoted against this oracle
inherits that spread.

### Markers arrive in runs

Adjacent markers — `XXXX XXXX XXXX` — usually mean one entity was replaced word by word rather
than three separate things being removed. The median narrative with any run has a longest run of
3; the p95 is 8.

**Consequence:** any span-level metric must merge adjacent markers into one span before
counting, or a single redacted street address inflates into four "correct" detections. That
merge rule is fixed in [DEFINITIONS.md](../DEFINITIONS.md) and applied everywhere.

---

## Three problems, all measured

### Problem 1 — it says *where*, never *what*

The original text is gone. `XXXX` could have been a name, a bank, a city, a dollar amount or a
date. We can measure whether a model found the right *span*; we cannot directly measure whether
it assigned the right *category*.

Partial mitigation: the words around a marker survive and carry much of the answer. Mining
123,416 non-date marker spans for their left context gives a usable signal —

| left context | share of spans | probably was |
|---|---:|---|
| `ending in XXXX` | 0.86% | card last four digits |
| `called XXXX` / `contacted XXXX` / `spoke with XXXX` | ~1.5% combined | person or organisation |
| `# XXXX`, `case # XXXX`, `number XXXX` | ~1.5% combined | reference or account number |
| `named XXXX`, `sincerely XXXX` | ~0.6% combined | person name |
| `$ XXXX` | 0.82% | dollar amount |

This is a **signal, not a labelling**. It narrows down what a marker probably was. Anywhere a
category count in this repository derives from it, it is labelled as an estimate.

### Problem 2 — it over-redacts, and much of what it removes is not personal information

This is worse than the brief anticipated, and it is the most important M0 finding.

| pattern | narratives | share | is it personal information? |
|---|---:|---:|---|
| `XXXX points` / `days` / `months` / `bureaus` | 16,891 | 7.5% | **No** — plain counts |
| `$ XXXX` | 5,344 | 2.4% | **No** — a dollar amount |
| `XXXX %` / `XXXX percent` | 967 | 0.4% | **No** — an interest rate |
| `XXXX CFR` / `XXXX USC` | 135 | 0.1% | **No** — a legal citation |
| `credit score from XXXX to XXXX` | 648 | 0.3% | **No** — a credit score |

Read in the sample by hand: a MacBook Pro redacted to `XXXX XXXX XXXX XXXX`, the number three
redacted in "all XXXX bureaus", and in one case the word *may* redacted out of a quoted
regulation — `"a card issuer XXXX not take any action"`.

**Why this matters:** a marker is not a reliable positive. If a model correctly declines to
redact the number three, the oracle scores that as a miss. Recall measured against raw markers
is therefore a *lower bound* on true recall, and the gap is not small. How this is handled is
fixed in [DEFINITIONS.md](../DEFINITIONS.md) before any measuring starts.

### Problem 3 — it under-redacts too, in a way that matters for the attack

Company names are frequently left in the clear:

| appears unredacted in | narratives | share |
|---|---:|---:|
| Chase | 57,453 | 25.5% |
| Capital One | 20,962 | 9.3% |
| Synchrony | 12,111 | 5.4% |
| Citibank | 9,678 | 4.3% |
| Barclays | 4,574 | 2.0% |

And, more consequential for M4:

| survives redaction | narratives | share |
|---|---:|---:|
| **An intact dollar amount `{$1234.00}`** | **99,427** | **44.2%** |
| A date marker `XX/XX/XXXX` | 85,241 | 37.9% |

The CFPB does not redact monetary amounts — it reformats them into braces and keeps them in
full. **An exact transaction amount is a strong join key against a transaction database.** Nearly
half of all narratives carry one, and 44.2% carry a median of two.

This single row is the preview of the whole project: the text has been scrubbed by a trained
human to a published standard, and it still contains the field an attacker would most want.

### Problem 3b — a broken template in the CFPB's own pipeline

**22,269 narratives (9.9%) contain the literal string `XX/XX/year>`.**

This is a malformed substitution — an unclosed placeholder tag that leaked into published text.
It is not documented anywhere. It has to be normalised before tokenisation or it fragments into
junk tokens, and it is a reminder that the scrubbing was a human-and-template process with the
failure modes of one.

---

## What this means for the project

The oracle survives, with conditions:

1. **Usable for recall.** 184,633 marked narratives is a large, real, in-domain signal, and the
   brief's stop condition is cleared nine times over.
2. **Only as a lower bound.** Over-redaction means some markers are not personal information, so
   measured recall understates true recall. The number is reported with that caveat attached
   every time it appears, not once in a footnote.
3. **Not usable alone for precision.** A model flagging something the CFPB left alone may be
   right or wrong, and the oracle cannot tell us which. Precision comes from injection (M2),
   where we know the answer because we wrote it.
4. **The inconsistency is a published number, not a disclaimer.** The 0.9%–16.7% spread goes in
   the results table.

---

## Reproducing this

```bash
./scripts/bootstrap.sh   # download + unpack, records which nightly build you got
make m0
```

| script | produces |
|---|---|
| `scripts/m0_scan_products.py` | `results/m0_product_counts.csv` |
| `scripts/m0_extract.py` | `results/m0_extract_summary.txt` |
| `scripts/m0_marker_stats.py` | `results/m0_marker_stats.txt`, `results/m0_marker_histogram.csv` |
| `scripts/m0_marker_context.py` | `results/m0_marker_contexts.csv`, `results/m0_sample_for_review.txt` |

Sampling uses seed `20260806` throughout. The corpus is re-published nightly, so exact counts
will drift for anyone downloading a different night's build — `data/raw/MANIFEST.txt` records
which one produced the numbers above.
