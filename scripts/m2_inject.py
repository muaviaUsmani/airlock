"""
M2: the injector — where exact ground truth comes from.

Takes narratives the CFPB already scrubbed clean (no XXXX markers at all), and
inserts personal information we generated ourselves at positions we record.

Those labels are facts, not opinions. We wrote them down when we put them in.
Since decision 003 removed hand-labelling, this file is the ONLY source of exact
ground truth in the project, and since M1 showed a model trained on marked text
just learns "XXXX -> redact", it is also the only viable training substrate.

WHAT MAKES A NARRATIVE MAP TO EXACTLY ONE CUSTOMER
--------------------------------------------------
Every injected value is DRAWN FROM one synthetic customer's record — their name,
their city, their employer, and the exact amount, date and merchant of a real
transaction of theirs. Invent the values instead and the narrative describes
nobody, and the M4 attack has nothing to find.

TWO LEAKS THIS FILE EXISTS TO PREVENT
-------------------------------------
Both are versions of the same failure: a model scoring well by learning something
other than what personal information looks like.

1. NARRATIVE LEAK. A clean narrative used for training never appears in an
   evaluation set. Enforced by splitting the pool before anything is generated.

2. TEMPLATE LEAK. The carrier sentences are formulaic. A model trained and tested
   on the same phrasings can memorise the phrasing rather than the PII — the same
   degenerate shortcut as "XXXX -> redact", one level up. So training uses four
   templates per category and evaluation uses two the model has never seen. The
   gap between held-out-template and seen-template performance is a published
   number, not an assumption. See DECISIONS/006-model-architecture.md.

TWO DISTRIBUTIONS, NOT ONE
--------------------------
Per decision 004: `natural` (measured corpus frequencies) drives the M4 headline;
`stratified` (equal power per category) drives per-category scoring. Neither is
hard-coded and every published number names its set.

A LIMITATION, STATED HERE BECAUSE IT LIVES HERE
-----------------------------------------------
Injected sentences are more uniform than organic prose. A real complaint weaves
personal information through its own argument; this splices in well-formed
carrier sentences. Injected PII is therefore somewhat EASIER to spot than the
real thing, and scores measured here are optimistic for every method equally.
The transfer check against real CFPB markers is what bounds that.

Reads:  data/interim/creditcard_narratives.parquet
        data/synthetic/{customers,transactions}.parquet
Writes: data/synthetic/injected_train.parquet
        data/synthetic/injected_natural.parquet
        data/synthetic/injected_stratified.parquet
        data/synthetic/injected_seen_templates.parquet   (leak-gap control)
        results/m2_injection_summary.txt
"""

from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import pandas as pd

from m2_templates import CATEGORIES, split as split_templates

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"
NARRATIVES = ROOT / "data" / "interim" / "creditcard_narratives.parquet"

SEED = 20260806
N_TRAIN = 15_000
N_EVAL = 4_000
SPANS_PER_NARRATIVE = (2, 7)
MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}")
FIELD = re.compile(r"\[\[(\w+)\]\]")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# --- the two distributions -------------------------------------------------
# NATURAL is renormalised from results/m2_category_distribution.csv over resolved
# PII spans. It is NOT the true corpus distribution — see decision 004.
NATURAL = {
    "DATE": 70.4, "ACCOUNT_ID": 7.0, "ORG_THIRD_PARTY": 6.1, "PERSON": 4.5,
    "TEMPORAL": 3.8, "AMOUNT": 2.5, "CASE_REF": 2.0, "CONTACT": 1.1,
    "LOCATION_FINE": 1.1, "PROTECTED_ATTR": 0.6, "MERCHANT": 0.4,
    "RELATIONSHIP": 0.1, "GOV_ID": 0.1, "LIFE_EVENT": 0.1, "EMPLOYER": 0.1,
    "HEALTH": 0.05,
}
STRATIFIED = {c: 100 / len(CATEGORIES) for c in CATEGORIES}

TIER = {
    "PERSON": 1, "ACCOUNT_ID": 1, "GOV_ID": 1, "CONTACT": 1, "CASE_REF": 1,
    "RELATIONSHIP": 2, "LOCATION_FINE": 2, "EMPLOYER": 2, "LIFE_EVENT": 2,
    "PROTECTED_ATTR": 2, "HEALTH": 2, "ORG_THIRD_PARTY": 2,
    "AMOUNT": 3, "DATE": 3, "MERCHANT": 3, "TEMPORAL": 3,
}

# NATURAL_V2 — decision 007. Tier 1 and 2 keep the marker-derived weights, but
# tier 3 frequencies are measured directly from surviving text
# (results/m2_tier3_survival.csv), because markers record what was REDACTED and
# tier 3 is by definition what the CFPB does not redact. Asking the marker
# oracle about money returns 2.5% when the text says 44.2% — a 17.7x
# under-estimate that lands straight on the M4 headline.
#
# Tier 3 is expressed as a PER-NARRATIVE probability, matching how it was
# measured (presence per narrative), rather than as a share of spans.
TIER3_PRESENCE = {"AMOUNT": 0.442, "DATE": 0.404, "MERCHANT": 0.148, "TEMPORAL": 0.047}
NATURAL_V2_T12 = {c: w for c, w in NATURAL.items() if TIER[c] in (1, 2)}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIMES = ["9am", "10:30am", "just after noon", "2pm", "4:45pm", "6pm"]

def resolve(field: str, cust: dict, txn: dict, rng: random.Random) -> str:
    y, m, d = txn["txn_date"].split("-")
    return {
        "person_first": cust["relative_name"].split()[0],
        "person_full": cust["full_name"],
        "last4": txn["last4"],
        "account_num": f"4{rng.randint(10**10, 10**11 - 1)}",
        "ssn": f"{rng.randint(100,899)}-{rng.randint(10,99)}-{rng.randint(1000,9999)}",
        "phone": cust["phone"],
        "email": cust["email"],
        "address": f"{cust['street']}, {cust['city']}, {cust['state']} {cust['zip']}",
        "case_ref": str(rng.randint(10**6, 10**7 - 1)),
        "relationship": cust["relationship_type"],
        "city": cust["city"],
        "city_state": f"{cust['city']}, {cust['state']}",
        "employer": cust["employer"],
        "life_event": cust["life_event"],
        "protected": cust["protected_attr"],
        "health": cust["health_procedure"],
        "bank": cust["third_party_bank"],
        "amount": f"${txn['amount']:.2f}",
        "date": rng.choice([f"{int(m)}/{int(d)}/{y}", f"{m}/{d}/{y}", f"{int(m)}/{int(d)}/{y[2:]}"]),
        "merchant": txn["merchant_name"],
        "weekday": rng.choice(WEEKDAYS),
        "time": rng.choice(TIMES),
    }[field]

def render(template: str, cat: str, cust: dict, txn: dict, rng: random.Random):
    """Split a template into literal parts and (category, value) parts."""
    parts, last = [], 0
    for m in FIELD.finditer(template):
        if m.start() > last:
            parts.append(template[last : m.start()])
        parts.append((cat, resolve(m.group(1), cust, txn, rng)))
        last = m.end()
    if last < len(template):
        parts.append(template[last:])
    return parts

def inject(narrative, cats, templates, cust, txn, rng):
    """
    Splice one carrier sentence per sampled category into the narrative at
    sentence boundaries, building the output in a single forward pass so recorded
    offsets are exact by construction rather than by later adjustment.
    """
    sentences = [s for s in SENT_SPLIT.split(narrative.strip()) if s] or [narrative.strip()]
    slots = sorted(rng.sample(range(len(sentences) + 1), min(len(cats), len(sentences) + 1)))
    plan: dict[int, list[str]] = {}
    for slot, cat in zip(slots, cats[: len(slots)]):
        plan.setdefault(slot, []).append(cat)

    out: list[str] = []
    spans: list[dict] = []
    pos = 0

    def emit(text: str) -> None:
        nonlocal pos
        out.append(text)
        pos += len(text)

    for i in range(len(sentences) + 1):
        for cat in plan.get(i, []):
            tmpl = rng.choice(templates[cat])
            for part in render(tmpl, cat, cust, txn, rng):
                if isinstance(part, tuple):
                    c, value = part
                    spans.append({
                        "start": pos, "end": pos + len(value),
                        "category": c, "tier": TIER[c], "value": value,
                    })
                    emit(value)
                else:
                    emit(part)
            emit(" ")
        if i < len(sentences):
            emit(sentences[i])
            if i < len(sentences) - 1:
                emit(" ")

    text = "".join(out)
    for s in spans:
        assert text[s["start"] : s["end"]] == s["value"], "offset drift — labels would be wrong"
    return text, spans

def build(name, dist, templates, narratives, customers, txn_by_cust, seed, tier3=None):
    """
    `dist` is a per-span multinomial. `tier3`, when given, is a dict of
    per-narrative Bernoulli probabilities applied on top — that is how tier 3
    survival was measured (presence per narrative), so that is how it is
    reproduced. See decision 007.
    """
    rng = random.Random(seed)
    rows = []
    for i, narrative in enumerate(narratives):
        cust = customers[i % len(customers)]
        txns = txn_by_cust.get(cust["customer_id"])
        if not txns:
            continue
        txn = dict(rng.choice(txns))
        txn["last4"] = f"{rng.randint(0, 9999):04d}"
        cats = rng.choices(list(dist), weights=list(dist.values()), k=rng.randint(*SPANS_PER_NARRATIVE))
        if tier3:
            cats = [c for c in cats if TIER[c] != 3]
            for cat, prob in tier3.items():
                if rng.random() < prob:
                    cats.append(cat)
            rng.shuffle(cats)
        text, spans = inject(narrative, cats, templates, cust, txn, rng)
        if spans:
            rows.append({
                "doc_id": f"{name}-{i:05d}", "customer_id": cust["customer_id"],
                "txn_id": txn["txn_id"], "text": text, "spans": spans, "n_spans": len(spans),
            })
    return pd.DataFrame(rows)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=N_TRAIN)
    ap.add_argument("--eval", type=int, default=N_EVAL)
    args = ap.parse_args()

    for p in (NARRATIVES, SYN / "customers.parquet", SYN / "transactions.parquet"):
        if not p.exists():
            print(f"missing {p} — run scripts/m2_transactions.py first")
            return 1

    train_t, eval_t = split_templates()

    df = pd.read_parquet(NARRATIVES, columns=["narrative"])
    clean = df[~df["narrative"].str.contains(MARKER, regex=True, na=False)]
    clean = clean[clean["narrative"].str.split().str.len().between(40, 600)]

    # DEDUPLICATE BEFORE SPLITTING. 17.3% of clean narratives are exact
    # duplicates — form-letter complaints submitted en masse, one of which
    # appears 181 times. Splitting without this puts identical text in both
    # train and eval, and the model scores on memorised documents. This was
    # caught by the leak assertion below rather than by inspection, which is
    # the argument for asserting it rather than trusting the split.
    before = len(clean)
    clean = clean.drop_duplicates(subset="narrative")
    print(f"deduplicated: {before:,} -> {len(clean):,} narratives "
          f"({before - len(clean):,} exact duplicates removed, {100*(before-len(clean))/before:.1f}%)")

    pool = clean.sample(frac=1.0, random_state=SEED)["narrative"].tolist()

    need = args.train + args.eval
    if len(pool) < need:
        print(f"only {len(pool):,} clean narratives, need {need:,}")
        return 1

    # NARRATIVE SPLIT — done before anything is generated, so it cannot leak.
    train_pool = pool[: args.train]
    eval_pool = pool[args.train : args.train + args.eval]
    assert not (set(train_pool) & set(eval_pool)), "narrative leak"

    customers = pd.read_parquet(SYN / "customers.parquet").to_dict("records")
    tdf = pd.read_parquet(SYN / "transactions.parquet")
    txn_by_cust: dict[str, list[dict]] = {}
    for r in tdf.to_dict("records"):
        txn_by_cust.setdefault(r["customer_id"], []).append(r)

    print(f"clean narratives: {len(clean):,} | train {len(train_pool):,} | eval {len(eval_pool):,}\n")

    sets = [
        # name,                dist,          templates, pool,       seed,     tier3
        ("train",              STRATIFIED,    train_t,   train_pool, SEED,     None),
        ("natural",            NATURAL,       eval_t,    eval_pool,  SEED + 1, None),
        ("natural_v2",         NATURAL_V2_T12, eval_t,   eval_pool,  SEED + 1, TIER3_PRESENCE),
        ("stratified",         STRATIFIED,    eval_t,    eval_pool,  SEED + 2, None),
        # Control: same eval narratives, but TRAIN templates. Difference against
        # `stratified` isolates template memorisation from everything else.
        ("seen_templates",     STRATIFIED,    train_t,   eval_pool,  SEED + 2, None),
    ]

    summaries = []
    for name, dist, tmpl, npool, seed, tier3 in sets:
        out = build(name, dist, tmpl, npool, customers, txn_by_cust, seed, tier3)
        out.to_parquet(SYN / f"injected_{name}.parquet", index=False)
        counts: dict[str, int] = {}
        for spans in out["spans"]:
            for s in spans:
                counts[s["category"]] = counts.get(s["category"], 0) + 1
        summaries.append((name, out, counts, sum(counts.values())))
        print(f"  {name:<16} {len(out):>6,} narratives  {sum(counts.values()):>7,} spans")

    L = ["M2 — injected sets", "=" * 64, "",
         f"seed: {SEED}   |   two distributions (decision 004), disjoint templates (decision 006)",
         "",
         "LEAK CONTROLS",
         "-" * 64,
         f"  narrative pools are disjoint: {len(train_pool):,} train vs {len(eval_pool):,} eval",
         "  carrier templates are disjoint: 4 per category for training,",
         "  2 per category held out for evaluation, asserted non-overlapping.",
         "",
         "  `seen_templates` is a control set: the SAME eval narratives rendered",
         "  with TRAINING templates. A model scoring well there and badly on",
         "  `stratified` has memorised phrasing, not learned personal information.",
         "  That gap is a headline diagnostic at M3, not a footnote.",
         ""]
    for name, out, counts, total in summaries:
        by_tier: dict[int, int] = {}
        for c, n in counts.items():
            by_tier[TIER[c]] = by_tier.get(TIER[c], 0) + n
        L += ["-" * 64, f"{name.upper()}", "",
              f"  narratives {len(out):>7,}   spans {total:>7,}   spans/narrative {total/max(len(out),1):>4.1f}",
              f"  tier 1 {100*by_tier.get(1,0)/max(total,1):>5.1f}%   "
              f"tier 2 {100*by_tier.get(2,0)/max(total,1):>5.1f}%   "
              f"tier 3 {100*by_tier.get(3,0)/max(total,1):>5.1f}%",
              ""]
        for c, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            L.append(f"    {c:<18} tier {TIER[c]}  {n:>7,}  {100*n/max(total,1):>5.1f}%")
        L.append("")
    L += ["-" * 64,
          "Every span above has an exact character offset recorded when it was",
          "written. The injector asserts text[start:end] == value for every span,",
          "so an offset bug fails the build rather than silently corrupting the",
          "labels every downstream number depends on."]
    out_txt = "\n".join(L)
    (RESULTS / "m2_injection_summary.txt").write_text(out_txt + "\n")
    print("\n" + out_txt[: out_txt.index("NATURAL")] if "NATURAL" in out_txt else out_txt)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
