"""
M0, step 4: work out WHAT was redacted, using the words around each marker.

The central weakness of the XXXX oracle is that it tells us where a redaction
happened but not what was removed. The original text is gone.

The words either side of a marker survive, though, and they carry a lot of the
answer. "I spoke to XXXX at the branch" and "my balance was XXXX" are different
categories, and the giveaway is the left context, not the marker.

So this script pulls the window around every marker in a seeded random sample and
counts which left-contexts occur most often. The output is the evidence base for
the category list in DEFINITIONS.md — the brief requires that list be built from
what is actually in the corpus rather than from a list someone invented.

This is a SIGNAL, not a labelling. It narrows down what a marker probably was; it
does not recover it. Any category counts derived from it are estimates and are
labelled as such wherever they appear.

Reads:  data/interim/creditcard_narratives.parquet
Writes: results/m0_marker_contexts.csv     (most common left contexts)
        results/m0_sample_for_review.txt   (100 narratives to read by hand)
"""

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
CONTEXTS = ROOT / "results" / "m0_marker_contexts.csv"
SAMPLE = ROOT / "results" / "m0_sample_for_review.txt"

# Fixed seed. Every number this project publishes has to be regenerable, and a
# sample is a number like any other.
SEED = 20260806
SAMPLE_FOR_CONTEXT = 20_000
SAMPLE_FOR_READING = 100

MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}(?![A-Za-z0-9])")

# Dates are redacted as XX/XX/XXXX — three markers joined by slashes, sometimes
# with the real year left in. They MUST be recognised as one span before
# anything else runs, or the pieces get treated as three separate redactions and
# the left context of the last piece comes out as "on xx/xx/", which is noise.
#
# Dates are also the one category we can already identify from the marker shape
# alone, so once matched they are masked out. What is left is the part of the
# corpus where we genuinely do not know what was removed — which is the part
# worth studying.
DATE_SPAN = re.compile(
    r"(?<![A-Za-z0-9])X{2}\s*/\s*X{2}\s*/\s*(?:X{2,4}|\d{2,4})(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])X{2}\s*/\s*(?:X{2,4}|\d{2,4})(?![A-Za-z0-9])"
)

# Collapse a run of markers into one span before looking at context. Otherwise
# the left context of the 2nd marker in "XXXX XXXX" is just "XXXX", which tells
# us nothing.
RUN = re.compile(r"(?<![A-Za-z0-9])X{2,}(?:[ \t]+X{2,})*(?![A-Za-z0-9])")

# Replacement for a masked date. Same character count is not needed here since
# we re-scan rather than map positions back.
DATE_PLACEHOLDER = " @DATE@ "

STOP = {"the", "a", "an", "my", "to", "of", "and", "in", "on", "at", "for", "with", "from", "i"}


def left_context(text: str, start: int, n: int = 3) -> str:
    """The n words immediately before a marker span, lowercased."""
    before = text[:start].split()
    return " ".join(w.lower().strip(".,;:!?\"'()") for w in before[-n:])


def main() -> int:
    if not IN.exists():
        print(f"missing {IN} — run scripts/m0_extract.py first", file=sys.stderr)
        return 1

    df = pd.read_parquet(IN, columns=["complaint_id", "narrative", "Issue"])
    marked = df[df["narrative"].str.contains(MARKER, regex=True, na=False)]

    sample = marked.sample(
        n=min(SAMPLE_FOR_CONTEXT, len(marked)), random_state=SEED
    )

    # --- left-context frequency -------------------------------------------
    trigrams: Counter[str] = Counter()
    bigrams: Counter[str] = Counter()
    unigrams: Counter[str] = Counter()
    n_spans = 0
    n_dates = 0

    for raw in sample["narrative"]:
        # Mask dates first so they stop fragmenting into three fake spans.
        text, n_sub = DATE_SPAN.subn(DATE_PLACEHOLDER, raw)
        n_dates += n_sub

        for m in RUN.finditer(text):
            n_spans += 1
            ctx = left_context(text, m.start(), 3).split()
            if ctx:
                unigrams[ctx[-1]] += 1
            if len(ctx) >= 2:
                bigrams[" ".join(ctx[-2:])] += 1
            if len(ctx) >= 3:
                trigrams[" ".join(ctx)] += 1

    rows = []
    for name, counter, keep in [
        ("unigram", unigrams, 120),
        ("bigram", bigrams, 120),
        ("trigram", trigrams, 120),
    ]:
        for phrase, count in counter.most_common(keep):
            # Bare stopwords as unigram context carry no category signal.
            if name == "unigram" and phrase in STOP:
                continue
            rows.append(
                {
                    "context_type": name,
                    "left_context": phrase,
                    "occurrences": count,
                    "share_of_spans": round(100.0 * count / max(n_spans, 1), 3),
                }
            )

    out = pd.DataFrame(rows)
    CONTEXTS.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(CONTEXTS, index=False)

    # --- narratives to read by hand ---------------------------------------
    # The brief requires 100 narratives be inspected by a person. Automated
    # context counting finds the common cases; reading finds the ones nobody
    # thought to look for.
    read_sample = marked.sample(n=SAMPLE_FOR_READING, random_state=SEED)
    lines = [
        "M0 — 100 credit-card narratives sampled for hand inspection",
        f"seed={SEED}  drawn from {len(marked):,} narratives containing >=1 marker",
        "",
        "Read these and note what kind of personal information each XXXX",
        "replaced. The category list in DEFINITIONS.md is built from this.",
        "=" * 72,
        "",
    ]
    for i, (_, row) in enumerate(read_sample.iterrows(), 1):
        lines.append(f"--- [{i:03d}] complaint {row['complaint_id']} | issue: {row['Issue']}")
        lines.append(row["narrative"].strip())
        lines.append("")

    SAMPLE.write_text("\n".join(lines) + "\n")

    print(f"date spans masked out:    {n_dates:,}")
    print(f"non-date spans analysed:  {n_spans:,} (from {len(sample):,} narratives)")
    print(f"\ntop left-contexts, dates excluded (unigram):")
    for phrase, count in unigrams.most_common(40):
        if phrase in STOP:
            continue
        print(f"  {count:>6,}  {100.0*count/max(n_spans,1):>5.2f}%  ...{phrase} XXXX")
    print(f"\ntop left-contexts, dates excluded (bigram):")
    for phrase, count in bigrams.most_common(30):
        print(f"  {count:>6,}  {100.0*count/max(n_spans,1):>5.2f}%  ...{phrase} XXXX")
    print(f"\nwrote {CONTEXTS}")
    print(f"wrote {SAMPLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
