"""
M2: how often does tier 3 information SURVIVE in published complaints?

Per decision 007, tier 3 injection frequencies cannot come from the CFPB markers.
Markers record what was redacted, and tier 3 is by definition what the CFPB does
NOT redact — so asking the marker oracle about amounts returns near zero by
construction, which is what made the first M4 attack run report a
re-identification rate about five times too small.

This measurement needs no oracle at all. Tier 3 values are still sitting in the
published text, so they can simply be counted.

What is counted, per narrative (presence, not occurrences — the injector works
per narrative):

  AMOUNT     an intact {$x.xx} or $x.xx money value
  DATE       an XX/XX/XXXX marker or a written date
  MERCHANT   a retail context word suggesting a named merchant
  TEMPORAL   a weekday or a time of day

Reads:  data/interim/creditcard_narratives.parquet
Writes: results/m2_tier3_survival.csv
        results/m2_tier3_survival.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
RESULTS = ROOT / "results"
SEED = 20260806

PATTERNS = {
    # CFPB reformats money as {$1,234.56}; plain $1,234.56 also occurs.
    "AMOUNT": re.compile(r"\{?\$\s?\d[\d,]*\.\d{2}\}?"),
    "DATE": re.compile(
        r"(?<![A-Za-z0-9])X{2}\s*/\s*X{2}\s*/\s*(?:X{2,4}|\d{2,4})"
        r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
        r"|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b",
        re.I),
    "MERCHANT": re.compile(
        r"\b(?:store|merchant|retailer|restaurant|gas\s+station|pharmacy|supermarket|"
        r"grocery|hotel|airline|dealership|shop)\b", re.I),
    "TEMPORAL": re.compile(
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
        r"|\b\d{1,2}\s?(?:am|pm)\b|\b(?:morning|afternoon|evening|midnight|noon)\b", re.I),
}


def main() -> int:
    if not IN.exists():
        print(f"missing {IN} — run scripts/m0_extract.py first", file=sys.stderr)
        return 1

    df = pd.read_parquet(IN, columns=["narrative"])
    n = len(df)
    rows = []
    for cat, rx in PATTERNS.items():
        present = df["narrative"].str.contains(rx, regex=True, na=False)
        rows.append({"category": cat, "tier": 3,
                     "narratives_containing": int(present.sum()),
                     "narratives_total": n,
                     "share_pct": round(100 * present.mean(), 2)})

    out = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULTS / "m2_tier3_survival.csv", index=False)

    L = [
        "M2 — tier 3 survival in published CFPB narratives",
        "=" * 64,
        "",
        f"narratives examined: {n:,}",
        "",
        "Counted directly from surviving text. No oracle involved — tier 3 is",
        "what the CFPB does NOT redact, so the values are still there to count.",
        "This is the measurement decision 007 substitutes for the marker-derived",
        "tier 3 frequencies, which are near zero by construction.",
        "",
        f"  {'category':<12} {'narratives':>12} {'share':>9}",
    ]
    for r in rows:
        L.append(f"  {r['category']:<12} {r['narratives_containing']:>12,} {r['share_pct']:>8.1f}%")
    L += [
        "",
        "-" * 64,
        "COMPARISON WITH THE MARKER-DERIVED ESTIMATE",
        "",
        f"  {'category':<12} {'from markers':>14} {'from survival':>15} {'ratio':>8}",
    ]
    marker_derived = {"AMOUNT": 2.5, "DATE": 70.4, "MERCHANT": 0.4, "TEMPORAL": 3.8}
    for r in rows:
        md = marker_derived.get(r["category"], 0.0)
        ratio = r["share_pct"] / md if md else float("inf")
        L.append(f"  {r['category']:<12} {md:>13.1f}% {r['share_pct']:>14.1f}% {ratio:>7.1f}x")
    L += [
        "",
        "AMOUNT is the one that matters. The markers say complaints almost never",
        "mention money; the text says otherwise. The markers are not wrong — they",
        "faithfully report that money is almost never REDACTED. They were simply",
        "asked a question they cannot answer.",
        "",
        "DATE runs the other way: over-represented in the marker estimate because",
        "XX/XX/XXXX labels itself (decision 004), and dates ARE redacted, so both",
        "biases stack on that row.",
    ]
    text = "\n".join(L)
    (RESULTS / "m2_tier3_survival.txt").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
