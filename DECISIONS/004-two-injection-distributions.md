# 004 — Two injection distributions, because one cannot do both jobs

**Date:** 2026-08-06
**Status:** Decided
**Blocks:** M2 (injection harness), M3 (the model), M4 (the attack), M5 (utility)
**Fork source:** Not in the brief. Surfaced by M2 measurement, per the brief's instruction that
unlisted forks be surfaced rather than picked.

---

## The question

The brief is explicit that the injection distribution must be derived from the corpus:

> *"The distribution of what we inject must be derived from the real corpus, not invented. What
> kinds of personal information actually appear in credit-card complaints, and how often?
> Measure that first... then inject at matching frequencies. Otherwise we are measuring
> performance on a distribution we made up."*

`scripts/m2_category_distribution.py` is that measurement. It does not support the instruction.

## What the measurement found

A 40-rule estimator over the 16 categories locked in `DEFINITIONS.md`, reading both sides of
every span, resolves **46.5%** of 119,261 marker spans. The remaining 53.5% are left `UNKNOWN`
rather than guessed, and the 300 commonest unresolved contexts are committed for inspection.

Coverage is not the problem. **Bias is.**

| | |
|---|---|
| `DATE` resolved by marker **shape** | 27,890 |
| `DATE` resolved by **context** | 8,902 |
| | **75.8% of `DATE` resolutions come from shape alone** |

`DATE` is the only category whose redaction preserves its own type signature — `XX/XX/XXXX`
still looks like a date. Nothing else does. A redacted name, employer, diagnosis and street all
become the same anonymous `XXXX`.

So `DATE` takes **70.4%** of resolved PII not because the corpus is mostly dates, but because
dates are the one category that survives redaction still labelled. The measured distribution
describes **what is easy to recover, not what was there.**

Injecting at those frequencies would produce a test set that is roughly 70% dates, with tier 2
at 8.1% overall — `RELATIONSHIP` 0.1%, `EMPLOYER` 0.1%, `HEALTH` 0.0%. Tier 2 contextual
identifiers are the entire claim of this project, and that distribution leaves nothing to
measure them with.

**This is irreducible, not a rule-quality gap.** The original text is gone, so any estimate of
what was there is biased toward whatever leaves traces. No better rule set fixes it.

A secondary cause was measured and is smaller than expected: 65.2% of `UNKNOWN` spans have
another marker inside their own context window, against 58.4% of resolved ones. Redacted context
contributes, but most unresolved spans sit in surviving prose that simply never says what was
removed.

## The decision

**Build two injection sets. Each answers a different question. Every published number names
which set produced it.**

| set | distribution | answers |
|---|---|---|
| **natural** | measured corpus frequencies, bias documented | *What is the real-world re-identification rate?* |
| **stratified** | equal power per category | *How well does each method handle each category?* |

The reasoning is that these are two different measurements wearing one name:

- **Re-identification rate depends on realistic co-occurrence.** A narrative carrying one of
  everything is far easier to link than a real complaint. The headline A%→B% therefore has to
  come from text shaped like the corpus, whatever its category mix.
- **Per-category recall needs N per cell.** A category appearing in 0.1% of spans yields
  confidence intervals too wide to support any claim, however realistic its frequency.

Using one set for both is the actual error. A natural set gives realistic rates and no
per-category power; a stratified set gives power and an uninterpretable headline. Running both
costs roughly 1.3x the harness work and one extra column in every results table.

## What each set is allowed to be used for

Binding, so that the split cannot later be used to pick whichever number looks better:

1. **The headline re-identification rate (M4) comes from `natural`.** Only.
2. **Per-category recall, precision and category accuracy (M3) come from `stratified`.** Only.
3. **Aggregate recall and precision are reported on both**, side by side. If they disagree
   sharply that is a finding about distribution sensitivity and gets written up.
4. **The utility measurement (M5) uses `natural`**, since it asks what a frontier model can still
   do with realistic redacted text.
5. Every table, chart and README figure carries the set name. A number without one is a bug.

## The bias that remains, and is published

`natural` inherits the resolvability bias in full — it is over-weighted toward `DATE` and
under-weighted toward every category that redaction leaves unlabelled. It is *not* the true
corpus distribution and is never described as one. It is the best available estimate, with a
known and documented direction of error.

The consequence for the headline is stated in `docs/05-attack.md`: because `natural`
under-represents tier 2 contextual identifiers relative to reality, the re-identification rate
it produces is most likely an **under**-estimate of real-world risk for the redaction methods
that handle tier 2 badly. That direction favours the baselines, not Airlock, so it is a
conservative error for this project's claim rather than a flattering one — which is the only
reason it is acceptable to publish at all.

## Consequences

- `scripts/m2_inject.py` takes a distribution as a parameter; neither set is hard-coded.
- Both sets are generated from the same seed and the same generator, so differences between them
  are distributional and nothing else.
- The stratified set fixes a minimum span count per category, so the smallest categories
  (`HEALTH`, `EMPLOYER`, `LIFE_EVENT`) are measurable at all.
- `docs/03-baselines.md` gains a re-run of all three M1 baselines on both sets — the first
  like-for-like comparison in the project, and the first that can score the regex baseline at
  all.
