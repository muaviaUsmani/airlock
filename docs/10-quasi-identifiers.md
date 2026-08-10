# What actually identifies people

**A claim about de-identification generally, not about this model.**

It is measured here on bank complaints and a synthetic transaction database, but
nothing in the argument is specific to banking. The same shape applies wherever
free text sits next to a structured record of events — health notes beside
admissions, support tickets beside order histories, legal discovery beside
timelines, telemetry beside accounts.

**Status: every number below is traced to a committed artifact in the
[provenance table](#provenance) at the end. Nothing here is asserted from
memory.**

---

## The claim, in one paragraph

Personal-information detectors remove names, addresses, card numbers and phone
numbers. Against a population of any realistic size, **those fields stop
identifying people.** What keeps identifying people is a combination of things no
detector touches and no definition calls personal: an amount, a date, a merchant.
At 160,000 customers a full name identifies **3.3%** of people and an
amount-date-merchant triple identifies **95.7%**. The redaction standard is
removing the wrong fields, and it gets more wrong as the database gets bigger.

## The measurement

A synthetic transaction database, generated from a fixed seed, with no real data
in it. For each field: what share of its values are held by **exactly one**
customer.

| customers | transactions | amount | amount+date | **amount+date+merchant** | full name | card last-4 |
|---:|---:|---:|---:|---:|---:|---:|
| 2,500 | 89,473 | 34.7% | 99.0% | **99.9%** | 95.5% | 85.8% |
| 10,000 | 359,375 | 30.7% | 96.0% | **99.7%** | 85.4% | 52.0% |
| 40,000 | 1,437,336 | 27.2% | 85.9% | **98.8%** | 49.3% | 4.1% |
| 160,000 | 5,763,243 | 24.7% | 61.1% | **95.7%** | 3.3% | 0.0% |

*`results/m2_uniqueness_curve.txt`, `scripts/m2_uniqueness_curve.py`, seed
20260806. The 10,000 row reproduces `results/m2_synthetic_summary.txt` exactly,
which is the check that the two agree.*

**Read the last three columns against each other.** As the population grows 64×:

- the quasi-identifier triple loses **4.2 points** (99.9% → 95.7%)
- a full name loses **92.2 points** (95.5% → 3.3%)
- a card's last four digits lose **85.8 points** (85.8% → 0.0%)

The fields a detector removes decay towards uselessness. The fields it ignores do
not. **At small scale the two look comparable, which is exactly why testing on a
small database would have hidden this.**

Individually the quasi-identifiers look harmless, and that is the trap. At 10,000
customers a date value is shared by **479 customers on average** and a merchant
by **1,329** — both 0.0% unique, both apparently safe to keep. Combined with an
amount they reach 99.7%.

## Why this is not a synthetic-data artifact

The obvious objection is that a generated database is unrealistically clean. Two
things argue against that mattering here.

**First, the direction of the bias is against us, not for us.** Real transaction
data is more skewed than generated data — real amounts cluster on round numbers
and common prices, real merchants follow a power law. Both effects *reduce*
uniqueness. If anything, this measurement understates how well names would do and
overstates collisions in the triple. The gap it reports is conservative.

**Second, the corresponding claim about the text is measured on real data.** The
narratives are real CFPB complaints, and the frequencies with which they mention
amounts, dates and merchants were counted from that real text — not assumed. That
is the next section.

## The same failure, in a real redaction standard

The CFPB publishes consumer complaints after redacting them to a published
standard, applied by trained staff. Counting what survives in **224,952** real
credit-card narratives:

| what survives | narratives | share |
|---|---:|---:|
| an intact dollar amount | 99,421 | **44.2%** |
| a date | 90,937 | 40.4% |
| a merchant name | 33,297 | 14.8% |

*`results/m0_marker_stats.txt` and `results/m2_tier3_survival.txt`.*

**This is not sloppiness, and calling it that would be the wrong lesson.** The
CFPB does not treat amounts as personal information at all — they are normalised
to a `{$x.xx}` form and deliberately kept. The standard is being applied
correctly. The standard is the problem.

An earlier version of this project's README described it as redactors "missing"
amounts. That framing was wrong and made the finding weaker than it is: a
professional standard, correctly executed, retains the single strongest join key
in the record.

### The part that makes this hard to notice

If you estimate how often complaints mention money by counting redaction markers
— the obvious approach, because markers are what a redactor left behind — you get
**2.5%**. Counting the actual text gives **44.2%**. A **17.7×** undercount.

| field | estimated from markers | counted from text | ratio |
|---|---:|---:|---:|
| amount | 2.5% | 44.2% | **17.7×** |
| merchant | 0.4% | 14.8% | **37.0×** |
| date | 70.4% | 40.4% | 0.6× |
| temporal | 3.8% | 4.7% | 1.2× |

*`results/m2_tier3_survival.txt`.*

**Markers only record what was removed.** The fields that enable
re-identification are precisely the ones nobody removes, so they leave no marker,
so any measurement built on markers is blind to them — and blind in proportion to
how dangerous they are. The two largest undercounts are the two strongest
quasi-identifiers.

In this project that single misestimate moved the headline re-identification rate
from **8.6% to 36.9%** ([decision 007](../DECISIONS/007-tier3-frequencies-cannot-come-from-markers.md)).
It is the largest single swing anything produced here.

## Does it survive an actual attack?

Uniqueness in a database is necessary but not sufficient — an attacker also has
to recover the values from redacted prose. Running the linkage attack against
redacted text:

| database | raw text | Presidio-redacted |
|---:|---:|---:|
| 10,000 customers | 36.9% | 1.2% |
| 40,000 customers | 14.3% | 0.1% |

*`results/m6_dbsize.txt`. The 2,500-customer row in that file is invalid and
excluded — the injected evaluation set references 4,000 customers, so at 2,500
the attack measured its own broken linkage rather than database size.*

Two honest observations:

- **Re-identification falls as the population grows** (36.9% → 14.3%), even
  though database uniqueness barely moves (99.7% → 98.8%). The bottleneck is not
  uniqueness; it is how much the attacker can recover from text, and the
  tolerances that recovery needs. More candidates means more false matches.
- **It has only been measured at two valid database sizes.** The 160,000 point is
  configured but has never been run, so the trend has two points and should not be
  extrapolated.

## What this does not establish

- **Not that PII detection is useless.** Presidio takes re-identification from
  36.9% to 1.2%. It helps a great deal. The claim is that it is not sufficient,
  not that it is worthless.
- **Not a real-world re-identification rate.** The database is synthetic, the
  linkage is exact-match with tolerances, and the attacker is assumed to hold a
  transaction record for the population. A real attacker has a different, usually
  worse, starting position.
- **Not measured at population scale.** The largest database here is 160,000
  customers. A national bank has tens of millions. The uniqueness trend is mild
  and smooth across the 64× measured, but that is an extrapolation past the data.
- **Not a claim about which fields a regulator should require removing.** This
  measures identifiability, not law, and nothing here satisfies any regulation.

## What would strengthen it

In rough order of value per hour:

1. **Run the 160,000-customer attack.** Already configured in
   `m6_ablate_dbsize.py`, never executed. Turns a two-point trend into three.
2. **Repeat the uniqueness curve on a skewed generator** — power-law merchants,
   round-number amount clustering. Tests the synthetic-data objection directly
   rather than arguing about it.
3. **Add a third quasi-identifier** (city, or transaction time-of-day) and see
   whether the triple is a floor or a plateau.

## Provenance

Every number above, and where it comes from. Anything not in this table does not
appear above.

| number | file | field | script | measured over |
|---|---|---|---|---|
| 99.9 / 99.7 / 98.8 / 95.7% triple uniqueness | `results/m2_uniqueness_curve.csv` | `amount+date+merchant_unique_pct` | `m2_uniqueness_curve.py` | 2.5k / 10k / 40k / 160k customers, seed 20260806 |
| 95.5 / 85.4 / 49.3 / 3.3% name uniqueness | `results/m2_uniqueness_curve.csv` | `full_name_unique_pct` | `m2_uniqueness_curve.py` | same |
| 85.8 / 52.0 / 4.1 / 0.0% last-4 uniqueness | `results/m2_uniqueness_curve.csv` | `card_last4_unique_pct` | `m2_uniqueness_curve.py` | same |
| 479 customers per date value | `results/m2_synthetic_summary.txt` | `txn date`, mean customers/value (478.7) | `m2_transactions.py` | 10,000 customers |
| 1,329 customers per merchant value | `results/m2_synthetic_summary.txt` | `merchant name`, mean customers/value (1328.8) | `m2_transactions.py` | 10,000 customers |
| 44.2% narratives with intact amount | `results/m0_marker_stats.txt` | 99,421 of 224,952 | `m0_marker_stats.py` | all credit-card narratives |
| 40.4% date, 14.8% merchant | `results/m2_tier3_survival.txt` | narratives / share | `m2_tier3_survival.py` | same corpus |
| 2.5% vs 44.2%, 17.7× | `results/m2_tier3_survival.txt` | markers vs survival | `m2_tier3_survival.py` | same corpus |
| 36.9% / 14.3% re-identification | `results/m6_dbsize.txt` | `U unique`, raw | `m6_ablate_dbsize.py` | 10k / 40k customers |
| 1.2% / 0.1% Presidio | `results/m6_dbsize.txt` | `U unique`, presidio | `m6_ablate_dbsize.py` | 10k / 40k customers |
| 8.6% → 36.9% swing | [decision 007](../DECISIONS/007-tier3-frequencies-cannot-come-from-markers.md) | — | `m4_attack.py` | 10,000 customers |

**Held fixed, and able to have decided the result:** the generator seed (20260806)
throughout; transactions per customer held constant as population grows, so only
the number of people changes; 400 merchants at every population, which caps
merchant diversity and therefore *understates* the triple's uniqueness at large
populations; a two-year date window; and exact-match linkage with ±$25 and ±7 day
tolerances in the attack.

Regenerate the curve with:

```bash
.venv/bin/python scripts/m2_uniqueness_curve.py
```

It generates each database in a temporary directory and never touches
`data/synthetic/`, so it is safe to run against a working checkout.
