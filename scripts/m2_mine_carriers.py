"""
M2 v2: mine carrier sentences from the corpus instead of writing them.

WHY
---
M3 found the encoder scoring 90.1% on injected text and 59.7% on real prose,
failing outright on ORG_THIRD_PARTY (0.8%) and TEMPORAL (7.9%). The diagnosis in
DECISIONS/008 is that it learned category-specific CARRIER CONTEXTS rather than
entity types — trained on "I also contacted Citibank to see if they could help",
it does not recognise the same bank name in prose a customer actually wrote.

The held-out-template control missed this because every template was written by
one generator in one register. Holding out four strings from six tests
memorisation of strings, not transfer to a different author.

So the fix is not more templates. It is templates we did not write.

HOW
---
The corpus already contains thousands of real carrier sentences: every sentence
containing an XXXX marker is a sentence a real customer wrote around a real piece
of personal information. Turning one into a template is a substitution:

    "I spoke to XXXX at the branch and she refused."
        -> "I spoke to [[person_full]] at the branch and she refused."

The label stays exact — we still choose the value and record where we put it —
but the surrounding prose is now the corpus's, in its own register, at its own
level of messiness, with thousands of distinct forms per category instead of six.

TWO RULES THAT MATTER
---------------------
1. A candidate sentence must contain EXACTLY ONE marker, and the template must
   contain no XXXX afterwards. A template carrying a leftover marker would
   reintroduce the "XXXX -> redact" shortcut directly into the training data.
2. Templates are split by SOURCE NARRATIVE, so a narrative's sentences cannot
   appear on both sides of the train/eval split.

Reads:  data/interim/creditcard_narratives.parquet
Writes: data/synthetic/carriers.json
        results/m2_carriers.txt
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from m2_category_distribution import MARKER_SPAN, classify

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"

SEED = 20260806
N_NARRATIVES = 60_000
MIN_WORDS, MAX_WORDS = 6, 45
TRAIN_FRACTION = 0.7
MAX_PER_CATEGORY = 4_000

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
ANY_MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}")

# Which generated field fills a slot of each estimated category.
SLOT = {
    "PERSON": "person_full", "ACCOUNT_ID": "last4", "GOV_ID": "ssn",
    "CONTACT": "phone", "CASE_REF": "case_ref", "RELATIONSHIP": "relationship",
    "LOCATION_FINE": "city", "EMPLOYER": "employer", "LIFE_EVENT": "life_event",
    "PROTECTED_ATTR": "protected", "HEALTH": "health",
    "ORG_THIRD_PARTY": "bank", "AMOUNT": "amount", "DATE": "date",
    "MERCHANT": "merchant", "TEMPORAL": "weekday",
}


# --- DETERMINING contexts only (decision 010) ------------------------------
# The estimator scored 23.8% because its rules mixed contexts that DETERMINE the
# type ("ending in XXXX" can only be an account) with ones that merely SUGGEST it
# ("with XXXX" could be a person, a bank or a city). Only the first kind is mined
# now. Coverage collapses; that is the trade, and it is published.
#
# Note what is absent: tier 2. There is rarely a phrase that names a contextual
# identifier — "my ex-husband XXXX" says the marker is a NAME, not a
# relationship. Mining cannot reach the categories that failed, which is why
# entity-site substitution exists for them.
DETERMINING = [
    ("ACCOUNT_ID", r"(ending|ends|end)\s+(in|with)\s*$"),
    ("ACCOUNT_ID", r"(account|acct|card)\s*(number|no|#)\s*:?\s*$"),
    ("ACCOUNT_ID", r"last\s+(four|4)\s+(digits?\s*)?(of\s+)?(my\s+)?(account|card)?\s*(is|are|:)?\s*$"),
    ("CASE_REF",   r"(case|claim|complaint|dispute|reference|ref|confirmation|ticket)\s*(number|no|#)\s*:?\s*$"),
    ("GOV_ID",     r"(social\s+security|ssn|tax\s*id|driver'?s?\s+licen[cs]e|passport)\s*(number|no|#)?\s*:?\s*$"),
    ("CONTACT",    r"(phone|telephone|fax|mobile|cell)\s*(number|no|#)\s*:?\s*$"),
    ("CONTACT",    r"(e-?mail)\s*(address)?\s*(is|:|at)?\s*$"),
    ("AMOUNT",     r"[${]\s*$"),
]
DETERMINING_RE = [(c, re.compile(p, re.I)) for c, p in DETERMINING]


def determining_category(sent: str, start: int, end: int) -> str | None:
    """Return a category only when surviving context leaves no alternative."""
    span = sent[start:end].strip()
    if DATE_SHAPE_RE.match(span):
        return "DATE"
    left = sent[max(0, start - 48) : start]
    for cat, pat in DETERMINING_RE:
        if pat.search(left):
            return cat
    return None


DATE_SHAPE_RE = re.compile(
    r"^X{2}\s*/\s*X{2}\s*/\s*(?:X{2,4}|\d{2,4})$|^X{2}\s*/\s*(?:X{2,4}|\d{2,4})$")


def choose_field(cat: str, sent: str, start: int) -> str:
    """
    Pick the slot field from context, not just from the category.

    Two defects the first pass showed, both visible in mined samples:

      "I then sent a email to XXXX"  -> CONTACT always became a phone number
      "pay off $ XXXX balance"       -> AMOUNT emitted "$47.13" after a "$",
                                        producing "$ $47.13"

    Both put text into training data that no customer would ever write, which is
    exactly the failure mode this whole rewrite exists to remove.
    """
    left = sent[max(0, start - 40) : start].lower()
    if cat == "AMOUNT":
        # Already preceded by a currency symbol: emit a bare number.
        return "amount_bare" if re.search(r"[${]\s*$", sent[:start]) else "amount"
    if cat == "CONTACT":
        if "email" in left or "e-mail" in left or "@" in left:
            return "email"
        if "address" in left or "mail" in left or "live" in left or "reside" in left:
            return "address"
        return "phone"
    if cat == "ACCOUNT_ID":
        return "last4" if re.search(r"(ending|ends|last\s*(four|4))\s*(in|with)?\s*$", left) else "account_num"
    return SLOT[cat]


def main() -> int:
    if not IN.exists():
        print(f"missing {IN}", file=sys.stderr)
        return 1

    rng = random.Random(SEED)
    df = pd.read_parquet(IN, columns=["narrative"])
    marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
    marked = marked.drop_duplicates(subset="narrative")
    texts = marked.sample(n=min(N_NARRATIVES, len(marked)), random_state=SEED)["narrative"].tolist()

    by_cat: dict[str, list[tuple[int, str]]] = defaultdict(list)
    rejected = Counter()

    for doc_id, text in enumerate(texts):
        for sent in SENT_SPLIT.split(text):
            sent = sent.strip()
            n_words = len(sent.split())
            if not (MIN_WORDS <= n_words <= MAX_WORDS):
                rejected["length"] += 1
                continue
            markers = list(MARKER_SPAN.finditer(sent))
            if len(markers) != 1:
                rejected["not exactly one marker"] += 1
                continue
            m = markers[0]
            cat = determining_category(sent, m.start(), m.end())
            if cat is None:
                rejected["context does not DETERMINE the category"] += 1
                continue
            field = choose_field(cat, sent, m.start())
            template = sent[: m.start()] + f"[[{field}]]" + sent[m.end():]
            # Rule 1: no leftover marker may survive into a template.
            if ANY_MARKER.search(template):
                rejected["leftover marker"] += 1
                continue
            if "{$" in template or "}" in template:
                rejected["formatting artefact"] += 1
                continue
            by_cat[cat].append((doc_id, template))

    # Rule 2: split by SOURCE NARRATIVE so sentences from one document cannot
    # straddle the split.
    doc_ids = sorted({d for v in by_cat.values() for d, _ in v})
    rng.shuffle(doc_ids)
    cut = int(len(doc_ids) * TRAIN_FRACTION)
    train_docs = set(doc_ids[:cut])

    train: dict[str, list[str]] = {}
    evl: dict[str, list[str]] = {}
    collisions = Counter()
    for cat, items in by_cat.items():
        seen_t, seen_e = set(), set()
        for d, t in items:
            (seen_t if d in train_docs else seen_e).add(t)
        # Splitting by source narrative is NOT sufficient on its own: the same
        # sentence recurs across different narratives (stock phrasings, form
        # letters), so a template string can reach both sides. Caught by the
        # injector's leak assertion rather than by inspection. Training keeps
        # the string, evaluation gives it up, so held-out means unseen.
        overlap = seen_t & seen_e
        collisions[cat] = len(overlap)
        seen_e -= overlap
        train[cat] = sorted(seen_t)[:MAX_PER_CATEGORY]
        evl[cat] = sorted(seen_e)[:MAX_PER_CATEGORY]

    usable = {c for c in SLOT if len(train.get(c, [])) >= 20 and len(evl.get(c, [])) >= 5}

    SYN.mkdir(parents=True, exist_ok=True)
    (SYN / "carriers.json").write_text(json.dumps(
        {"train": {c: train[c] for c in usable}, "eval": {c: evl[c] for c in usable}}, indent=1))

    L = ["M2 v2 — carrier sentences mined from the corpus", "=" * 68, "",
         f"narratives scanned: {len(texts):,}   seed {SEED}", "",
         "Real sentences real customers wrote, with the redacted span turned",
         "into a slot. The label stays exact — we still choose the value and",
         "record where we put it — but the surrounding prose is the corpus's.",
         "",
         "Replaces six hand-written templates per category, all in one register,",
         "which DECISIONS/008 identified as the reason the encoder learned",
         "carrier contexts instead of entity types.", "",
         f"  {'category':<18} {'train':>8} {'eval':>8}  {'usable?':>8}"]
    for cat in SLOT:
        t, e = len(train.get(cat, [])), len(evl.get(cat, []))
        L.append(f"  {cat:<18} {t:>8,} {e:>8,}  {'yes' if cat in usable else 'NO':>8}")
    L += ["", "-" * 68, "TEMPLATE STRINGS REACHING BOTH SIDES OF THE SPLIT", "",
          "Splitting by source narrative does not make template STRINGS disjoint:",
          "the same sentence recurs across narratives. Removed from the",
          "evaluation side so held-out means unseen.", ""]
    for cat, n in collisions.most_common():
        if n:
            L.append(f"  {cat:<18} {n:>6,} removed from eval")
    L += ["",
          f"usable categories: {len(usable)} of {len(SLOT)}",
          "",
          "A category needs >=20 training and >=5 evaluation carriers to be",
          "usable. Those below stay on the hand-written templates, and every",
          "results table says which category came from which source — otherwise",
          "the comparison would be confounded by the thing it is measuring.",
          "",
          "-" * 68, "SENTENCES REJECTED, AND WHY", ""]
    for reason, n in rejected.most_common():
        L.append(f"  {reason:<28} {n:>9,}")
    L += ["",
          "'not exactly one marker' dominates because CFPB scrubbing is dense —",
          "most sentences carrying personal information carry several redactions.",
          "Those are unusable: a template with a leftover XXXX would inject the",
          "'XXXX -> redact' shortcut straight into the training data.", ""]

    ex = []
    for cat in sorted(usable)[:6]:
        if train.get(cat):
            ex.append(f"  {cat}:\n    {train[cat][len(train[cat])//2][:110]}")
    if ex:
        L += ["-" * 68, "SAMPLES", ""] + ex

    out = "\n".join(L)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "m2_carriers.txt").write_text(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
