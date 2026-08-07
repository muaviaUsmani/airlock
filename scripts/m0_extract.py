"""
M0, step 2: pull the credit-card complaints with written narratives out of the
16.9M-row CFPB file and save them somewhere fast to re-read.

Two judgement calls are baked in here, both visible on purpose:

1. The CFPB renamed its top-level category partway through the corpus history.
   "Credit card" (older rows) and "Credit card or prepaid card" (newer rows) both
   contain credit-card complaints, so both are kept.

2. The newer category also contains things that are not credit cards — prepaid
   cards, gift cards, payroll cards, government benefit cards. Those are dropped.
   A complaint about a gift card is a different domain with different personal
   information in it, and mixing them in would blur what the model is tuned for.
   The counts for the dropped rows are printed so the exclusion stays auditable.

Reads:  data/raw/complaints.csv
Writes: data/interim/creditcard_narratives.parquet
        results/m0_extract_summary.txt
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "complaints.csv"
OUT = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
SUMMARY = ROOT / "results" / "m0_extract_summary.txt"

NARRATIVE = "Consumer complaint narrative"

# Both spellings of the top-level category carry real credit-card complaints.
CREDIT_CARD_PRODUCTS = {"Credit card", "Credit card or prepaid card"}

# Sub-products inside those categories that are NOT credit cards.
NOT_CREDIT_CARD = {
    "General-purpose prepaid card",
    "Government benefit card",
    "Gift card",
    "Payroll card",
    "Student prepaid card",
}

KEEP_COLS = [
    "Complaint ID",
    "Date received",
    "Product",
    "Sub-product",
    "Issue",
    "Sub-issue",
    NARRATIVE,
    "Company",
    "State",
    "ZIP code",
    "Company response to consumer",
]

CHUNK = 200_000


def main() -> int:
    if not RAW.exists():
        print(f"missing {RAW} — run ./scripts/bootstrap.sh first", file=sys.stderr)
        return 1

    kept: list[pd.DataFrame] = []
    n_scanned = 0
    n_dropped_prepaid = 0

    reader = pd.read_csv(RAW, usecols=KEEP_COLS, chunksize=CHUNK, dtype=str, low_memory=False)

    for i, chunk in enumerate(reader):
        n_scanned += len(chunk)

        in_product = chunk["Product"].isin(CREDIT_CARD_PRODUCTS)
        has_narr = chunk[NARRATIVE].notna() & (chunk[NARRATIVE].str.strip() != "")
        candidate = chunk[in_product & has_narr]

        is_prepaid = candidate["Sub-product"].isin(NOT_CREDIT_CARD)
        n_dropped_prepaid += int(is_prepaid.sum())
        kept.append(candidate[~is_prepaid])

        if i % 20 == 0:
            print(f"  {n_scanned:,} rows scanned", flush=True)

    df = pd.concat(kept, ignore_index=True)
    df = df.rename(columns={NARRATIVE: "narrative", "Complaint ID": "complaint_id"})
    # Sorting by complaint id makes the output byte-identical across runs, which
    # is what lets downstream sampling be reproducible from a seed alone.
    df = df.sort_values("complaint_id").reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    lines = [
        f"rows scanned:                 {n_scanned:,}",
        f"credit-card narratives kept:  {len(df):,}",
        f"prepaid/gift/etc dropped:     {n_dropped_prepaid:,}",
        "",
        "kept by sub-product:",
    ]
    for sub, n in df["Sub-product"].fillna("(none)").value_counts().items():
        lines.append(f"  {sub:<45} {n:>8,}")

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    SUMMARY.write_text(text + "\n")
    print("\n" + text)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
