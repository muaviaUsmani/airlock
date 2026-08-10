"""M2 — how quasi-identifier uniqueness moves with population size.

WHY THIS EXISTS
---------------
`results/m2_synthetic_summary.txt` reports that an amount, a date and a merchant
together are 99.7% unique. That figure is quoted throughout the project as the
reason it exists at all. It was measured against exactly one population —
10,000 customers — and never against any other.

Uniqueness is a property of a value ACROSS a population, so it necessarily falls
as the population grows: more people means more chances to collide. A uniqueness
figure quoted without its population is therefore not a number, in exactly the
way a re-identification rate is not (see results/m6_dbsize.txt). This script
measures the curve so the claim can be stated with its dependency attached
rather than as a bare percentage.

WHAT THIS IS NOT
----------------
This is not the re-identification ablation. `m6_ablate_dbsize.py` measures
whether the ATTACK succeeds at different database sizes, and it is floored at
10,000 customers because the injected evaluation set references customers
C000000-C003999 — below that, the attack measures its own broken linkage.

That floor does not apply here. This measures a property of the database alone,
with no injected set and no attack involved, so small populations are legitimate
and informative.

SAFETY
------
`m2_transactions` writes the canonical synthetic database when it runs. This
script redirects its output paths to a temporary directory for the whole sweep,
so `data/synthetic/` is never touched. That is deliberately stronger than
regenerating and restoring afterwards: nothing to restore means nothing to get
wrong if it is interrupted.

Writes: results/m2_uniqueness_curve.txt
        results/m2_uniqueness_curve.csv
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

RESULTS = ROOT / "results"

# Ascending, so the trend is readable straight down the column.
SIZES = [2_500, 10_000, 40_000, 160_000]


def uniqueness(series: pd.Series, owner: pd.Series) -> tuple[float, float]:
    """Share of values held by exactly one customer, and mean customers/value.

    Identical to the helper in m2_transactions so the 10,000-customer row of
    this table reproduces m2_synthetic_summary.txt exactly. If it ever stops
    doing so, one of the two has drifted.
    """
    g = pd.DataFrame({"v": series, "o": owner}).groupby("v")["o"].nunique()
    return 100 * (g == 1).mean(), g.mean()


def measure(T, n: int, tmp: Path) -> dict:
    T.N_CUSTOMERS = n
    t0 = time.time()
    T.main()
    cdf = pd.read_parquet(tmp / "customers.parquet")
    cardsdf = pd.read_parquet(tmp / "cards.parquet")
    tdf = pd.read_parquet(tmp / "transactions.parquet")

    pair = tdf["amount"].astype(str) + "|" + tdf["txn_date"]
    triple = pair + "|" + tdf["merchant_name"]

    row = {"customers": n, "transactions": len(tdf), "seconds": round(time.time() - t0, 1)}
    for label, s, o in (
        ("amount", tdf["amount"], tdf["customer_id"]),
        ("date", tdf["txn_date"], tdf["customer_id"]),
        ("merchant", tdf["merchant_name"], tdf["customer_id"]),
        ("amount+date", pair, tdf["customer_id"]),
        ("amount+date+merchant", triple, tdf["customer_id"]),
        ("full_name", cdf["full_name"], cdf["customer_id"]),
        ("card_last4", cardsdf["last4"], cardsdf["customer_id"]),
    ):
        u, m = uniqueness(s, o)
        row[f"{label}_unique_pct"] = round(u, 2)
        row[f"{label}_mean_customers"] = round(m, 1)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default=",".join(str(s) for s in SIZES))
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",") if s]

    import m2_transactions as T

    tmp = Path(tempfile.mkdtemp(prefix="airlock-uniq-"))
    orig_out, orig_results, orig_n = T.OUT, T.RESULTS, T.N_CUSTOMERS
    rows = []
    try:
        # Redirect BOTH, or the sweep would overwrite the canonical summary too.
        T.OUT, T.RESULTS = tmp, tmp
        for n in sizes:
            print(f"  generating {n:,} customers...", flush=True)
            rows.append(measure(T, n, tmp))
            r = rows[-1]
            print(f"    amount+date+merchant {r['amount+date+merchant_unique_pct']:5.1f}% unique"
                  f"   ({r['transactions']:,} transactions, {r['seconds']}s)", flush=True)
    finally:
        T.OUT, T.RESULTS, T.N_CUSTOMERS = orig_out, orig_results, orig_n
        shutil.rmtree(tmp, ignore_errors=True)

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "m2_uniqueness_curve.csv", index=False)

    L = ["M2 — quasi-identifier uniqueness against population size", "=" * 70, "",
         "'unique' is the share of values held by exactly one customer. It falls",
         "as the population grows, because more people means more collisions --",
         "so a uniqueness figure without its population attached is not a number.",
         "",
         "Same generator and seed as the canonical database; the 10,000 row",
         "reproduces results/m2_synthetic_summary.txt exactly.", "",
         f"  {'customers':>10} {'txns':>10} {'amount':>9} {'a+date':>9} "
         f"{'a+d+merch':>11} {'name':>8} {'last4':>8}"]
    for r in rows:
        L.append(f"  {r['customers']:>10,} {r['transactions']:>10,} "
                 f"{r['amount_unique_pct']:>8.1f}% {r['amount+date_unique_pct']:>8.1f}% "
                 f"{r['amount+date+merchant_unique_pct']:>10.1f}% "
                 f"{r['full_name_unique_pct']:>7.1f}% {r['card_last4_unique_pct']:>7.1f}%")

    first, last = rows[0], rows[-1]
    drop = first["amount+date+merchant_unique_pct"] - last["amount+date+merchant_unique_pct"]
    L += ["", "-" * 70, "READING IT", "",
          f"  Across a {last['customers']//first['customers']}x population increase",
          f"  ({first['customers']:,} -> {last['customers']:,}), the amount+date+merchant",
          f"  combination loses {drop:.1f} points of uniqueness, ending at "
          f"{last['amount+date+merchant_unique_pct']:.1f}%.", ""]
    if drop < 5:
        L += ["  The combination stays sharply identifying at every population",
              "  measured. The headline claim does not depend on a small database —",
              "  which is the objection it would otherwise attract.", ""]
    else:
        L += ["  The combination degrades materially with population. Any claim made",
              "  from it must name the population it was measured at.", ""]
    L += ["  Note what does NOT move: name and card last-4 are properties of a",
          "  customer, not of a transaction, so their uniqueness falls for a",
          "  different reason -- more customers sharing a name space.", "",
          "  This measures the DATABASE only. Whether an attacker can exploit it",
          "  from redacted text is m6_ablate_dbsize.py, which is floored at 10,000",
          "  customers because below that the injected set outruns the database and",
          "  the attack measures its own broken linkage instead."]

    text = "\n".join(L)
    (RESULTS / "m2_uniqueness_curve.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
