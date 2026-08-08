# What each component actually contributed

Every ablation here removes or changes one thing and measures the effect. Where a result turned
out to be an artefact of the test rather than the thing being tested, that is said plainly rather
than quietly dropped.

---

## Database size — does the headline survive a bigger population?

**The objection this answers.** `docs/05-attack.md` reports re-identification falling from 36.9%
to 0.2%, measured against a synthetic database of 10,000 customers. The obvious challenge is that
uniqueness is easy in a small population, and a real bank has millions. If the result only holds
at toy scale, it is not a result.

Transactions per customer are held constant, so the only thing changing is how many people the
attacker has to tell apart.

| customers | raw U | raw K (<5) | presidio U | attacker FP |
|---:|---:|---:|---:|---:|
| 10,000 | **36.9%** | 44.3% | 1.2% | 0.5% |
| 40,000 | **14.3%** | 29.9% | 0.1% | 1.4% |

**Re-identification roughly halves when the database quadruples.** That is the expected direction
and it is a real limit on the headline: **the absolute numbers in this project are conditioned on
a 10,000-customer database and are optimistic for the attacker.** At a bank with millions of
customers, raw re-identification from amount + date + merchant would be substantially lower than
36.9%.

Two things survive the scaling, and they are what the claim actually rests on:

1. **The ordering is unchanged.** Raw leaks far more than Presidio at both sizes, and the gap
   between them widens rather than closes (30x at 10,000, 143x at 40,000).
2. **K falls more slowly than U.** At 40,000 the attacker uniquely identifies 14.3% but narrows
   to fewer than five customers in **29.9%** of cases — more than twice as often. Growing the
   population stops an attacker naming one person long before it stops them naming a handful, and
   a shortlist of four is not privacy.

### The gap in this table, stated rather than hidden

**Airlock was not run at 40,000.** The sweep was limited to raw and Presidio because each
additional method costs a full 28-configuration pass and the run already took 90 minutes at 4x
database size. So the headline's Airlock row has no 40,000-customer counterpart, and the honest
version of the claim is: *the ordering holds at scale, and Airlock's absolute 0.2% is measured at
10,000.*

### A row that was measured and must not be published

| customers | raw U | |
|---:|---:|---|
| 2,500 | 19.1% | **invalid — do not quote** |

Read naively this says smaller databases are *safer*, which is backwards.

The cause is broken linkage, not privacy. The injector assigns customers round-robin, so 4,000
narratives reference customers `C000000`–`C003999`. Regenerating the database at 2,500 customers
left **1,500 narratives (37.5%) pointing at customers that no longer existed**, and the attacker
cannot find someone who is not there. It was measuring the test's own breakage.

It is recorded here because the failure is instructive: the number was plausible, pointed in an
interesting direction, and would have been quotable. What caught it was checking linkage
integrity rather than reading the output — `0.0%` missing customers at 40,000 against 37.5% at
2,500.

`scripts/m6_ablate_dbsize.py` now refuses any size below the injection baseline. Sizes may only
grow, which is safe because the generator draws customers sequentially from a fixed seed, so
customer *i* is identical at every N.

---

## Injector hardening — carriers, values, hard negatives

Covered in detail in [docs/04-model.md](04-model.md) and
[decision 010](../DECISIONS/010-hardening-the-injector.md). Summarised here because it is the
largest single effect measured in this project.

Same architecture, same hyper-parameters, same test set. Only the training data changed:

| | authored carriers | hardened | delta |
|---|---:|---:|---:|
| recall on real prose | 47.3% ±17.1 | 70.5% ±1.0 | **+23.2** |
| F1 | 62.0% ±15.9 | 81.8% ±0.5 | +19.8 |
| `ORG_THIRD_PARTY` | 0.1% | 45.0% | **+44.9** |
| seed-to-seed spread | ±17.1 | ±1.0 | **17x tighter** |

**`TEMPORAL` is the control nobody designed.** It is the one well-powered category that received
no real carriers — determining-context mining found none, and entity-site substitution did not
cover weekdays. It is also the only well-powered category that did not improve (6.6% → 3.1%).
Treatment applied, large gains; treatment withheld, nothing. That is the closest this project
comes to a controlled experiment.

---

## Still to run

- **Capacity** — micro (22M) vs base (184M) vs large (434M) on identical data.
- **Architecture** — encoder vs generative at matched size (large 434M vs Qwen3 0.6B).
- **Hard negatives**, **value-pool diversity**, and **entity-site carriers** removed individually,
  to attribute the hardening gain to its parts rather than to the bundle.
