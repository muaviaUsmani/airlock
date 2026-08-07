"""
M0, step 3: characterise the XXXX markers — the free labels this project depends on.

Background, for a reader who has not seen the corpus:

Before publishing a complaint, the CFPB has a human remove anything that could
identify the customer and leaves a run of X's in its place. So a published
narrative reads like:

    "I called XXXX on XX/XX/XXXX about my XXXX XXXX card ending in XXXX"

Each of those runs marks a spot where a trained human decided personal
information was present. That is a redaction oracle we did not have to pay for,
on real text, in exactly the domain we care about.

It is also a NOISY oracle, in three specific ways this script measures:

  1. It says WHERE, never WHAT. "XXXX" could have been a name, a bank, a city,
     or a card number. We can measure whether a model finds the right span; we
     cannot directly measure whether it assigned the right category.

  2. It over-redacts. The CFPB standard is conservative and applied word by word,
     so company names and common nouns get scrubbed alongside real identifiers.
     The "marker share" numbers below quantify how much of the average narrative
     has been replaced.

  3. It is inconsistent between narratives. Some are scrubbed to near-unreadability,
     others barely at all. The spread in markers-per-100-words is the measure of
     that inconsistency, and it is the single number that decides whether these
     labels can carry a recall metric at all.

This script also counts the narratives with NO markers, because those are the raw
material for M2: to get exact labels we inject personal information we generated
ourselves into text that has already been scrubbed clean.

Reads:  data/interim/creditcard_narratives.parquet
Writes: results/m0_marker_stats.txt
        results/m0_marker_histogram.csv
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
OUT = ROOT / "results" / "m0_marker_stats.txt"
HIST = ROOT / "results" / "m0_marker_histogram.csv"

# A redaction marker is a run of two or more capital X's standing as its own
# token. Requiring 2+ avoids catching the pronoun-ish stray "X" and the "X" in
# things like "Series X". Requiring a token boundary avoids matching inside
# words such as "XXXtreme" that occasionally appear in merchant names.
MARKER = re.compile(r"(?<![A-Za-z0-9])X{2,}(?![A-Za-z0-9])")

# Dates are redacted with a distinctive shape: XX/XX/XXXX, sometimes with the
# real year left in (XX/XX/2023). Worth counting separately because a date is
# the one redaction category whose type we CAN recover from the marker alone.
DATE_MARKER = re.compile(r"(?<![A-Za-z0-9])X{2}/X{2}/(?:X{2,4}|\d{4})(?![A-Za-z0-9])")

# The CFPB wraps monetary amounts in braces — {$60.00}. This is a formatting
# convention, NOT a redaction: the amount is still there in full. It matters
# because an amount that survives redaction is exactly the kind of detail the
# M4 linkage attack will try to join on.
AMOUNT = re.compile(r"\{\$[\d,]+\.?\d*\}")

# Consecutive markers separated only by whitespace, e.g. "XXXX XXXX XXXX".
# A run of 3 usually means one multi-word thing (a full name, a street address)
# was scrubbed token by token, so runs tell us about the granularity of the
# scrubbing rather than the number of distinct entities removed.
RUN = re.compile(r"(?:(?<![A-Za-z0-9])X{2,}(?![A-Za-z0-9])[ \t]*){2,}")


def pct(numerator: int, denominator: int) -> str:
    return f"{100.0 * numerator / denominator:.1f}%" if denominator else "n/a"


def describe(series: pd.Series, name: str, fmt: str = "{:.1f}") -> list[str]:
    """Five-number summary. Means alone hide the inconsistency we are looking for."""
    q = series.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return [
        f"  {name}",
        f"    mean {fmt.format(series.mean())}   "
        f"p5 {fmt.format(q[0.05])}   p25 {fmt.format(q[0.25])}   "
        f"median {fmt.format(q[0.5])}   p75 {fmt.format(q[0.75])}   p95 {fmt.format(q[0.95])}   "
        f"max {fmt.format(series.max())}",
    ]


def main() -> int:
    if not IN.exists():
        print(f"missing {IN} — run scripts/m0_extract.py first", file=sys.stderr)
        return 1

    df = pd.read_parquet(IN, columns=["complaint_id", "narrative"])
    n = len(df)
    text = df["narrative"]

    words = text.str.split().str.len()
    n_markers = text.map(lambda s: len(MARKER.findall(s)))
    n_dates = text.map(lambda s: len(DATE_MARKER.findall(s)))
    n_amounts = text.map(lambda s: len(AMOUNT.findall(s)))
    n_runs = text.map(lambda s: len(RUN.findall(s)))
    longest_run = text.map(
        lambda s: max((len(m.split()) for m in RUN.findall(s)), default=0)
    )

    # How much of the text has been replaced. This is the over-redaction measure.
    marker_share = (n_markers / words.clip(lower=1)) * 100

    has_marker = n_markers > 0
    clean = n_markers == 0

    L: list[str] = []
    L.append("M0 — CFPB credit-card narratives: XXXX marker statistics")
    L.append("=" * 62)
    L.append("")
    L.append(f"narratives:                        {n:>10,}")
    L.append(f"  with >=1 redaction marker:       {int(has_marker.sum()):>10,}  ({pct(int(has_marker.sum()), n)})")
    L.append(f"  with no marker at all:           {int(clean.sum()):>10,}  ({pct(int(clean.sum()), n)})")
    L.append(f"  with >=5 markers:                {int((n_markers >= 5).sum()):>10,}  ({pct(int((n_markers >= 5).sum()), n)})")
    L.append("")
    L.append("The 'no marker at all' group is the raw material for M2 injection:")
    L.append("text already scrubbed by a human, into which we insert personal")
    L.append("information at positions we record ourselves.")
    L.append("")
    L.append("-" * 62)
    L.append("LENGTH")
    L += describe(words, "words per narrative", "{:.0f}")
    L.append("")
    L.append("-" * 62)
    L.append("MARKER DENSITY  (the recall oracle's raw material)")
    L += describe(n_markers, "markers per narrative", "{:.0f}")
    L += describe(n_markers[has_marker], "markers per narrative (marked only)", "{:.0f}")
    L.append("")
    L.append("-" * 62)
    L.append("OVER-REDACTION  (how much of the text is gone)")
    L += describe(marker_share, "markers as % of words")
    L += describe(marker_share[has_marker], "markers as % of words (marked only)")
    L.append("")
    L.append("The spread between p5 and p95 here is the inconsistency the brief")
    L.append("warns about. A tight spread means the scrubbing standard was applied")
    L.append("evenly and recall against it is meaningful. A wide spread means some")
    L.append("narratives were scrubbed far harder than others, and a model that")
    L.append("matches the average will look wrong on both tails.")
    L.append("")
    L.append("-" * 62)
    L.append("GRANULARITY  (were multi-word things scrubbed token by token?)")
    L += describe(n_runs, "adjacent-marker runs per narrative", "{:.1f}")
    L += describe(longest_run[n_runs > 0], "longest run, in markers (narratives with a run)", "{:.1f}")
    L.append("")
    L.append("A run of 3+ usually means one entity — a full name, a street address —")
    L.append("was replaced word by word. Runs inflate any per-marker count, so span")
    L.append("level metrics must merge them. That merge rule goes in DEFINITIONS.md.")
    L.append("")
    L.append("-" * 62)
    L.append("WHAT SURVIVED REDACTION")
    L.append(f"  narratives containing a date marker (XX/XX/XXXX):  {int((n_dates > 0).sum()):>8,}  ({pct(int((n_dates > 0).sum()), n)})")
    L.append(f"  narratives containing an intact amount ({{$x.xx}}): {int((n_amounts > 0).sum()):>8,}  ({pct(int((n_amounts > 0).sum()), n)})")
    L += describe(n_amounts[n_amounts > 0], "intact amounts per narrative (where present)", "{:.1f}")
    L.append("")
    L.append("Amounts are NOT redacted by the CFPB — they are reformatted and kept.")
    L.append("An exact transaction amount is a strong join key against a transaction")
    L.append("database, so this row is a preview of the M4 attack surface.")
    L.append("")

    text_out = "\n".join(L)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text_out + "\n")

    # Histogram for plotting later, and so the distribution shape is auditable
    # rather than only summarised.
    hist = (
        pd.DataFrame({"markers": n_markers})
        .value_counts("markers")
        .sort_index()
        .rename("narratives")
        .reset_index()
    )
    hist.to_csv(HIST, index=False)

    print(text_out)
    print(f"wrote {OUT}")
    print(f"wrote {HIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
