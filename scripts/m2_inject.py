"""
M2: the injector — where exact ground truth comes from.

Takes narratives the CFPB already scrubbed clean (no XXXX markers at all), and
inserts personal information we generated ourselves at positions we record.

Those labels are facts, not opinions. We wrote them down when we put them in.
Since decision 003 removed hand-labelling, this file is the ONLY source of exact
ground truth in the project, and since M1 showed a model trained on marked text
just learns "XXXX -> redact", it is also the only viable training substrate. It
carries more weight than the brief's one paragraph suggests.

WHAT MAKES A NARRATIVE MAP TO EXACTLY ONE CUSTOMER
--------------------------------------------------
Every injected value is DRAWN FROM one synthetic customer's record — their name,
their city, their employer, and the exact amount, date and merchant of a real
transaction of theirs. Invent the values instead and the narrative describes
nobody, and the M4 attack has nothing to find.

TWO DISTRIBUTIONS, NOT ONE
--------------------------
Per decision 004, this runs twice:

  natural     measured corpus frequencies. Over-weighted toward DATE because
              XX/XX/XXXX is the only category that survives redaction still
              labelled. Drives the M4 headline, where realistic co-occurrence
              is what matters.

  stratified  equal power per category. Drives per-category scoring, where a
              category at 0.1% would have confidence intervals too wide to
              support any claim.

Neither is hard-coded — the distribution is a parameter. Every published number
names which set produced it.

A LIMITATION, STATED HERE BECAUSE IT LIVES HERE
-----------------------------------------------
Injected sentences are more uniform than organic prose. A real complaint weaves
personal information through its own argument; this splices in well-formed
carrier sentences. That makes injected PII somewhat EASIER to spot than the real
thing, so precision and recall measured here are optimistic for every method
equally. docs/08-limitations.md carries this.

Reads:  data/interim/creditcard_narratives.parquet
        data/synthetic/{customers,transactions}.parquet
Writes: data/synthetic/injected_natural.parquet
        data/synthetic/injected_stratified.parquet
        results/m2_injection_summary.txt
"""

from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"
NARRATIVES = ROOT / "data" / "interim" / "creditcard_narratives.parquet"

SEED = 20260806
N_NARRATIVES = 4_000
SPANS_PER_NARRATIVE = (2, 7)
MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}")

# --- the two distributions -------------------------------------------------
# NATURAL comes from results/m2_category_distribution.csv, renormalised over the
# resolved PII spans. It is NOT the true corpus distribution — see decision 004.
NATURAL = {
    "DATE": 70.4, "ACCOUNT_ID": 7.0, "ORG_THIRD_PARTY": 6.1, "PERSON": 4.5,
    "TEMPORAL": 3.8, "AMOUNT": 2.5, "CASE_REF": 2.0, "CONTACT": 1.1,
    "LOCATION_FINE": 1.1, "PROTECTED_ATTR": 0.6, "MERCHANT": 0.4,
    "RELATIONSHIP": 0.1, "GOV_ID": 0.1, "LIFE_EVENT": 0.1, "EMPLOYER": 0.1,
    "HEALTH": 0.05,
}
CATEGORIES = list(NATURAL)
STRATIFIED = {c: 100 / len(CATEGORIES) for c in CATEGORIES}

TIER = {
    "PERSON": 1, "ACCOUNT_ID": 1, "GOV_ID": 1, "CONTACT": 1, "CASE_REF": 1,
    "RELATIONSHIP": 2, "LOCATION_FINE": 2, "EMPLOYER": 2, "LIFE_EVENT": 2,
    "PROTECTED_ATTR": 2, "HEALTH": 2, "ORG_THIRD_PARTY": 2,
    "AMOUNT": 3, "DATE": 3, "MERCHANT": 3, "TEMPORAL": 3,
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIMES = ["9am", "10:30am", "just after noon", "2pm", "4:45pm", "the evening"]


def fmt_date(iso: str, rng: random.Random) -> str:
    y, m, d = iso.split("-")
    return rng.choice([f"{int(m)}/{int(d)}/{y}", f"{m}/{d}/{y}", f"{int(m)}/{int(d)}/{y[2:]}"])


def build_sentence(cat: str, cust: dict, txn: dict, rng: random.Random):
    """
    Return (parts) where each part is either a literal string or a
    (category, value) tuple. Offsets are computed by the caller so that what we
    record is exactly what lands in the text.
    """
    P = lambda v: (cat, str(v))  # noqa: E731

    if cat == "PERSON":
        return rng.choice([
            ["I spoke with a representative named ", P(cust["relative_name"].split()[0]), " who promised to call back."],
            ["My name is ", P(cust["full_name"]), " and I have banked with them for years."],
            ["The supervisor, ", P(cust["full_name"].split()[0] + " " + cust["last_name"]), ", refused to escalate it."],
        ])
    if cat == "ACCOUNT_ID":
        return rng.choice([
            ["The card ending in ", P(txn["last4"]), " is the one that was charged."],
            ["My account number ", P(f"4{rng.randint(10**10, 10**11 - 1)}"), " has been active since 2019."],
        ])
    if cat == "GOV_ID":
        return ["They asked me to confirm my social security number ",
                P(f"{rng.randint(100,899)}-{rng.randint(10,99)}-{rng.randint(1000,9999)}"), " over the phone."]
    if cat == "CONTACT":
        return rng.choice([
            ["They can reach me at ", P(cust["phone"]), " during business hours."],
            ["I sent the documents from ", P(cust["email"]), " and never got a reply."],
            ["My mailing address is ", P(f"{cust['street']}, {cust['city']}, {cust['state']} {cust['zip']}"), "."],
        ])
    if cat == "CASE_REF":
        return ["I was given case number ", P(f"{rng.randint(10**6, 10**7 - 1)}"), " and told to wait."]
    if cat == "RELATIONSHIP":
        return rng.choice([
            ["My ", P(cust["relationship_type"]), " opened this account without telling me."],
            ["I had to ask my ", P(cust["relationship_type"]), " to help me read the statement."],
        ])
    if cat == "LOCATION_FINE":
        return rng.choice([
            ["I went into the ", P(f"{cust['city']}"), " branch to sort it out in person."],
            ["The nearest office is in ", P(f"{cust['city']}, {cust['state']}"), " and it was closed."],
        ])
    if cat == "EMPLOYER":
        return ["I have worked at ", P(cust["employer"]), " for eleven years and my pay is direct deposited."]
    if cat == "LIFE_EVENT":
        return ["This started right after ", P(cust["life_event"]), " and I could not keep up."]
    if cat == "PROTECTED_ATTR":
        return ["I am a ", P(cust["protected_attr"]), " and I felt they took advantage of that."]
    if cat == "HEALTH":
        return ["The account was opened to pay for ", P(cust["health_procedure"]), " which I could not afford outright."]
    if cat == "ORG_THIRD_PARTY":
        return ["I also contacted ", P(cust["third_party_bank"]), " to see if they could help."]
    if cat == "AMOUNT":
        return rng.choice([
            ["There is a charge of ", P(f"${txn['amount']:.2f}"), " that I never authorised."],
            ["They took ", P(f"${txn['amount']:.2f}"), " out without any notice."],
        ])
    if cat == "DATE":
        return ["This happened on ", P(fmt_date(txn["txn_date"], rng)), " and I reported it the same week."]
    if cat == "MERCHANT":
        return ["The charge shows as ", P(txn["merchant_name"]), " which I do not recognise."]
    if cat == "TEMPORAL":
        return ["It was a ", P(rng.choice(WEEKDAYS)), " and I called at ", ("TEMPORAL", rng.choice(TIMES)), "."]
    raise ValueError(cat)


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def inject(narrative: str, cats: list[str], cust: dict, txn: dict, rng: random.Random):
    """
    Splice one carrier sentence per category into the narrative at sentence
    boundaries, building the output in a single forward pass so recorded offsets
    are exact by construction rather than by later adjustment.
    """
    sentences = [s for s in SENT_SPLIT.split(narrative.strip()) if s]
    if not sentences:
        sentences = [narrative.strip()]

    slots = sorted(rng.sample(range(len(sentences) + 1), min(len(cats), len(sentences) + 1)))
    cats = cats[: len(slots)]
    plan: dict[int, list[str]] = {}
    for slot, cat in zip(slots, cats):
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
            for part in build_sentence(cat, cust, txn, rng):
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
    # Assert the labels really are facts: every recorded span must contain
    # exactly the value we claim to have written there.
    for s in spans:
        assert text[s["start"] : s["end"]] == s["value"], "offset drift — labels would be wrong"
    return text, spans


def sample_categories(dist: dict[str, float], k: int, rng: random.Random) -> list[str]:
    cats, weights = list(dist), list(dist.values())
    return rng.choices(cats, weights=weights, k=k)


def build(name: str, dist: dict[str, float], narratives, customers, txn_by_cust, rng):
    rows = []
    for i, narrative in enumerate(narratives):
        cust = customers[i % len(customers)]
        txns = txn_by_cust.get(cust["customer_id"])
        if not txns:
            continue
        txn = dict(rng.choice(txns))
        txn["last4"] = f"{rng.randint(0, 9999):04d}"
        k = rng.randint(*SPANS_PER_NARRATIVE)
        cats = sample_categories(dist, k, rng)
        text, spans = inject(narrative, cats, cust, txn, rng)
        if not spans:
            continue
        rows.append({
            "doc_id": f"{name}-{i:05d}",
            "customer_id": cust["customer_id"],
            "txn_id": txn["txn_id"],
            "text": text,
            "spans": spans,
            "n_spans": len(spans),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=N_NARRATIVES)
    args = ap.parse_args()

    for p in (NARRATIVES, SYN / "customers.parquet", SYN / "transactions.parquet"):
        if not p.exists():
            print(f"missing {p}")
            return 1

    rng = random.Random(SEED)
    df = pd.read_parquet(NARRATIVES, columns=["narrative"])
    clean = df[~df["narrative"].str.contains(MARKER, regex=True, na=False)]
    clean = clean[clean["narrative"].str.split().str.len().between(40, 600)]
    narratives = clean.sample(n=min(args.n, len(clean)), random_state=SEED)["narrative"].tolist()

    customers = pd.read_parquet(SYN / "customers.parquet").to_dict("records")
    tdf = pd.read_parquet(SYN / "transactions.parquet")
    txn_by_cust: dict[str, list[dict]] = {}
    for r in tdf.to_dict("records"):
        txn_by_cust.setdefault(r["customer_id"], []).append(r)

    print(f"clean narratives available: {len(clean):,}  |  using {len(narratives):,}\n")

    summaries = []
    for name, dist in [("natural", NATURAL), ("stratified", STRATIFIED)]:
        out = build(name, dist, narratives, customers, txn_by_cust, random.Random(SEED))
        out.to_parquet(SYN / f"injected_{name}.parquet", index=False)

        counts = {}
        for spans in out["spans"]:
            for s in spans:
                counts[s["category"]] = counts.get(s["category"], 0) + 1
        total = sum(counts.values())
        uniq_cust = out["customer_id"].nunique()
        summaries.append((name, out, counts, total, uniq_cust))
        print(f"{name:<11} {len(out):,} narratives, {total:,} spans, {uniq_cust:,} distinct customers")

    L = ["M2 — injected evaluation sets", "=" * 62, "",
         f"seed: {SEED}   |   per decision 004, two distributions", ""]
    for name, out, counts, total, uniq in summaries:
        L += [
            "-" * 62,
            f"{name.upper()}",
            "",
            f"  narratives          {len(out):>8,}",
            f"  injected spans      {total:>8,}",
            f"  spans/narrative     {total/max(len(out),1):>8.1f}",
            f"  distinct customers  {uniq:>8,}",
            "",
            f"  {'category':<18} {'tier':>4} {'spans':>8} {'share':>8}",
        ]
        for c, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            L.append(f"  {c:<18} {TIER[c]:>4} {n:>8,} {100*n/max(total,1):>7.1f}%")
        by_tier: dict[int, int] = {}
        for c, n in counts.items():
            by_tier[TIER[c]] = by_tier.get(TIER[c], 0) + n
        L.append("")
        for t in (1, 2, 3):
            L.append(f"  tier {t}: {by_tier.get(t,0):>7,}  ({100*by_tier.get(t,0)/max(total,1):>5.1f}%)")
        L.append("")
    L += [
        "-" * 62,
        "Every span above has an exact character offset, recorded when it was",
        "written. The injector asserts text[start:end] == value for every span,",
        "so an offset bug fails the build rather than silently corrupting the",
        "labels every downstream number depends on.",
    ]
    out_txt = "\n".join(L)
    (RESULTS / "m2_injection_summary.txt").write_text(out_txt + "\n")
    print("\n" + out_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
