"""
M0, step 1: find out what is actually in the CFPB file before filtering anything.

The CFPB has renamed its product categories over the years, so the label for a
credit-card complaint is not one fixed string. Rather than guess which strings to
filter on, this script reads the whole file once and counts, for every
(Product, Sub-product) pair, how many rows exist and how many of those rows have a
written customer narrative attached. The output of this script is what tells us
which categories to keep in step 2.

Reads:  data/raw/complaints.csv
Writes: results/m0_product_counts.csv
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "complaints.csv"
OUT = ROOT / "results" / "m0_product_counts.csv"

# The narrative column is the customer's own free text. It is the only column
# this project cares about; everything else is metadata used for filtering.
NARRATIVE = "Consumer complaint narrative"
COLS = ["Product", "Sub-product", NARRATIVE]

CHUNK = 200_000


def main() -> int:
    if not RAW.exists():
        print(f"missing {RAW} — run the download first", file=sys.stderr)
        return 1

    counts: dict[tuple[str, str], list[int]] = {}
    rows_seen = 0

    reader = pd.read_csv(
        RAW,
        usecols=COLS,
        chunksize=CHUNK,
        dtype=str,
        low_memory=False,
    )

    for i, chunk in enumerate(reader):
        rows_seen += len(chunk)
        # Missing sub-product is meaningful (older rows often have none), so it
        # gets its own visible label rather than being dropped.
        product = chunk["Product"].fillna("(missing)")
        subproduct = chunk["Sub-product"].fillna("(none)")
        # A narrative counts as present only if it has non-whitespace content.
        has_narr = chunk[NARRATIVE].notna() & (chunk[NARRATIVE].str.strip() != "")

        grouped = pd.DataFrame(
            {"product": product, "subproduct": subproduct, "has_narr": has_narr}
        ).groupby(["product", "subproduct"], dropna=False)["has_narr"].agg(["size", "sum"])

        for (p, s), row in grouped.iterrows():
            slot = counts.setdefault((p, s), [0, 0])
            slot[0] += int(row["size"])
            slot[1] += int(row["sum"])

        if i % 10 == 0:
            print(f"  {rows_seen:,} rows scanned", flush=True)

    out = pd.DataFrame(
        [
            {"product": p, "subproduct": s, "complaints": n, "with_narrative": w}
            for (p, s), (n, w) in counts.items()
        ]
    ).sort_values("with_narrative", ascending=False)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"\ntotal rows: {rows_seen:,}")
    print(f"total with narrative: {out['with_narrative'].sum():,}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
