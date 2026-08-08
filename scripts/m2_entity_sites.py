"""
M2: carrier sentences for the categories mining cannot reach.

WHY THIS EXISTS
---------------
Decision 010 restricted carrier mining to contexts that DETERMINE a category
("ending in XXXX" can only be an account). That works for tier 1, AMOUNT and
DATE — and yields exactly zero for every tier 2 category, because English rarely
contains a phrase naming a contextual identifier. "my ex-husband XXXX" tells you
the marker was a NAME, not a relationship.

Tier 2 is what this project exists to catch, and it is where the encoder failed
worst: ORG_THIRD_PARTY 0.8%, PERSON 50.8% on real prose. So those categories need
real carriers from somewhere other than marker context.

THE APPROACH
------------
Clean narratives — real complaints the CFPB never redacted — still contain real
entities. Run entity recognition over them, and substitute our synthetic value
where a real entity of that type already stood:

    "I called Capital One and they transferred me twice."
        -> "I called [[bank]] and they transferred me twice."

Real prose. Real syntactic position. Exact label, because we choose what goes in.
No category estimation anywhere in the chain.

THE BIAS, AND WHY IT IS ACCEPTABLE
----------------------------------
Sites are chosen by spaCy, so spaCy is later tested partly on positions it picked
itself, which inflates the spaCy baseline.

That is the CONSERVATIVE direction for this project — it makes the baseline
harder to beat, not easier. A win against an inflated baseline is still a win; a
loss is not evidence of much. This is reported wherever these categories appear
rather than buried.

THE GUARD THAT MATTERS
----------------------
DEFINITIONS.md is explicit that the company the complaint is filed against is NOT
personal information — it is a structured field of the record. Every complaint
carries that company name, so an ORG site is skipped when it matches it.
Without this, the injector would label the complained-about company as
third-party PII and train the model on a rule DEFINITIONS.md forbids.

Reads:  data/interim/creditcard_narratives.parquet
Writes: data/synthetic/entity_carriers.json
        results/m2_entity_sites.txt
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"

SEED = 20260806
N_NARRATIVES = 25_000
MIN_WORDS, MAX_WORDS = 6, 45
TRAIN_FRACTION = 0.7
MAX_PER_CATEGORY = 5_000

MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# spaCy label -> (our category, the field that fills the slot)
LABEL_MAP = {
    "PERSON": ("PERSON", "person_full"),
    "ORG": ("ORG_THIRD_PARTY", "bank"),
    "GPE": ("LOCATION_FINE", "city"),
    "LOC": ("LOCATION_FINE", "city"),
    "FAC": ("LOCATION_FINE", "city"),
    # TIME covers "2pm", "the morning". DATE covers "Tuesday", "last week".
    # TEMPORAL was the one well-powered category that got NO real carriers, and
    # the only one that did not improve — 3.1% against 96.8% for both baselines.
    # Determining-context mining cannot reach it (no English phrase announces
    # "a weekday follows"), so it needs the same entity-site treatment that took
    # ORG_THIRD_PARTY from 0.1% to 45.0%.
    "TIME": ("TEMPORAL", "time"),
}

# spaCy tags weekday names as DATE, not TIME, so they are matched explicitly.
WEEKDAY_RE = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b")

# Generic tokens spaCy frequently mislabels as organisations in this corpus.
STOPWORD_ENTITIES = {
    "cfpb", "consumer financial protection bureau", "ftc", "irs", "congress",
    "credit card", "visa", "mastercard", "amex", "american express",
    "equifax", "experian", "transunion", "trans union", "fico",
}


def normalise(name: str) -> str:
    n = re.sub(r"[^a-z ]", " ", name.lower())
    n = re.sub(r"\b(inc|llc|na|n a|corp|corporation|company|co|holdings?|group|bank|usa|us)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def main() -> int:
    if not IN.exists():
        print(f"missing {IN}", file=sys.stderr)
        return 1
    import spacy

    rng = random.Random(SEED)
    df = pd.read_parquet(IN, columns=["narrative", "Company"])
    clean = df[~df["narrative"].str.contains(MARKER, regex=True, na=False)]
    clean = clean.drop_duplicates(subset="narrative")
    clean = clean[clean["narrative"].str.split().str.len().between(40, 600)]
    sample = clean.sample(n=min(N_NARRATIVES, len(clean)), random_state=SEED)

    nlp = spacy.load("en_core_web_lg", disable=["lemmatizer", "textcat"])
    by_cat: dict[str, list[tuple[int, str]]] = {}
    kept, skipped = Counter(), Counter()

    docs = nlp.pipe(sample["narrative"].tolist(), batch_size=48)
    for doc_id, (doc, company) in enumerate(zip(docs, sample["Company"].tolist())):
        company_norm = normalise(str(company))
        for sent in doc.sents:
            text = sent.text.strip()
            if not (MIN_WORDS <= len(text.split()) <= MAX_WORDS):
                continue
            ents = [e for e in sent.ents if e.label_ in LABEL_MAP]
            for m in WEEKDAY_RE.finditer(text):
                ents.append(type("E", (), {"label_": "TIME", "text": m.group(0),
                                           "start_char": sent.start_char + m.start()})())
            if not ents:
                skipped["no usable entity"] += 1
                continue
            # Previously this required EXACTLY one entity, which threw away
            # 88,538 sentences and left PERSON with 474 carriers against
            # ORG_THIRD_PARTY's 5,000. One entity is picked per sentence and the
            # rest are left alone, so the label stays exact while the yield rises.
            e = ents[doc_id % len(ents)]
            cat, field = LABEL_MAP[e.label_]
            surface = e.text.strip()
            low = surface.lower()

            if cat == "ORG_THIRD_PARTY":
                # DEFINITIONS.md: the company complained against is NOT PII.
                norm = normalise(surface)
                if norm and company_norm and (norm in company_norm or company_norm in norm):
                    skipped["ORG is the complained-about company"] += 1
                    continue
                if low in STOPWORD_ENTITIES or norm in STOPWORD_ENTITIES:
                    skipped["ORG is a regulator/bureau/network"] += 1
                    continue
            if len(surface) < 3 or surface.isdigit():
                skipped["degenerate entity"] += 1
                continue

            s = e.start_char - sent.start_char
            template = text[:s] + f"[[{field}]]" + text[s + len(e.text):]
            if MARKER.search(template):
                skipped["marker in template"] += 1
                continue
            by_cat.setdefault(cat, []).append((doc_id, template))
            kept[cat] += 1

    # Split by source narrative, then enforce string-level disjointness — the
    # same sentence recurs across narratives and would otherwise straddle it.
    doc_ids = sorted({d for v in by_cat.values() for d, _ in v})
    rng.shuffle(doc_ids)
    train_docs = set(doc_ids[: int(len(doc_ids) * TRAIN_FRACTION)])

    train, evl, collisions = {}, {}, Counter()
    for cat, items in by_cat.items():
        st, se = set(), set()
        for d, t in items:
            (st if d in train_docs else se).add(t)
        collisions[cat] = len(st & se)
        se -= st
        train[cat] = sorted(st)[:MAX_PER_CATEGORY]
        evl[cat] = sorted(se)[:MAX_PER_CATEGORY]

    usable = {c for c in train if len(train[c]) >= 50 and len(evl[c]) >= 20}
    SYN.mkdir(parents=True, exist_ok=True)
    (SYN / "entity_carriers.json").write_text(json.dumps(
        {"train": {c: train[c] for c in usable}, "eval": {c: evl[c] for c in usable}}, indent=1))

    L = ["M2 — carriers from real entity sites in clean narratives", "=" * 70, "",
         f"narratives scanned: {len(sample):,}   seed {SEED}", "",
         "For the tier 2 categories carrier mining cannot reach, because English",
         "rarely names a contextual identifier. Real prose, real syntactic",
         "position, exact label — no category estimation anywhere.", "",
         f"  {'category':<18} {'train':>8} {'eval':>8}  {'usable?':>8}"]
    for cat in sorted(set(c for c, _ in LABEL_MAP.values())):
        t, e = len(train.get(cat, [])), len(evl.get(cat, []))
        L.append(f"  {cat:<18} {t:>8,} {e:>8,}  {'yes' if cat in usable else 'NO':>8}")
    L += ["", "-" * 70, "SITES SKIPPED", ""]
    for reason, n in skipped.most_common():
        L.append(f"  {reason:<38} {n:>9,}")
    L += ["",
          "'ORG is the complained-about company' is the guard that matters.",
          "DEFINITIONS.md says that company is NOT personal information — it is a",
          "structured field of the record. Without the guard the injector would",
          "label it third-party PII and train a rule DEFINITIONS.md forbids.",
          "",
          "-" * 70, "THE BIAS THIS INTRODUCES", "",
          "Sites are chosen by spaCy, so spaCy is later tested partly on positions",
          "it selected. That INFLATES the spaCy baseline — the conservative",
          "direction for this project, since it makes the baseline harder to beat.",
          "Reported wherever these categories appear.", ""]
    ex = []
    for cat in sorted(usable):
        if train.get(cat):
            ex.append(f"  {cat}:\n    {train[cat][len(train[cat]) // 2][:110]}")
    if ex:
        L += ["-" * 70, "SAMPLES", ""] + ex

    out = "\n".join(L)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "m2_entity_sites.txt").write_text(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
