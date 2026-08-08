"""
M6 ablation: does the re-identification rate survive a bigger database?

WHY THIS IS THE FIRST ABLATION
------------------------------
docs/05-attack.md flags it as the caveat most likely to be quoted against the
headline: amount+date is 96.0% unique in a 10,000-customer database, and
uniqueness necessarily falls as the population grows. A bank with ten million
customers would see the same quasi-identifiers narrow less sharply.

If the re-identification rate collapses with scale, the headline is an artefact
of a small synthetic database and has to be stated as one. If it degrades
gently, the finding holds for realistic populations. Either way it is cheap to
measure and expensive to leave unmeasured.

Needs no GPU and no retraining — it regenerates the adversary's database at
several sizes and re-runs the attack. Transaction count per customer is held
constant, so the only thing changing is how many people the attacker must
distinguish between.

Writes: results/m6_dbsize.csv
        results/m6_dbsize.txt
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
# Sizes must be >= the number of distinct customers the injected set references,
# or the ablation measures its own broken linkage instead of database size.
#
# The injector assigns customers round-robin, so 4,000 narratives touch customers
# C000000-C003999. Regenerating the database at 2,500 leaves 1,500 narratives
# (37.5%) pointing at customers that no longer exist — the attack cannot find
# them, U collapses, and it looks like "small databases are safer". They are not;
# the test was broken. That run reported 19.1% against 36.9% at 10,000, which is
# backwards from the real effect and would have been published as a finding.
#
# Sizes only grow from the injection baseline. Customer i is identical at every
# N because the generator draws sequentially from a fixed seed, so linkage is
# preserved upward and every row stays comparable.
SIZES = [10_000, 40_000, 160_000]


def main() -> int:
    import m2_transactions as T

    inj = pd.read_parquet(ROOT / "data" / "synthetic" / "injected_natural_v2.parquet")
    needed = int(inj["customer_id"].str.lstrip("C").astype(int).max()) + 1
    too_small = [n for n in SIZES if n < needed]
    if too_small:
        raise SystemExit(
            f"sizes {too_small} are below the {needed:,} customers the injected set "
            f"references; that would measure broken linkage, not database size")

    rows = []
    original = T.N_CUSTOMERS
    # try/finally: this script REGENERATES the canonical synthetic database at
    # each size. If it dies halfway the repo would be left holding a database of
    # the wrong size, and every later M4 run would silently use it. Restoring in
    # a finally block makes that impossible rather than unlikely.
    try:
        rows = _sweep(T, rows)
    finally:
        T.N_CUSTOMERS = original
        T.main()
        print(f"\ncanonical database restored at {original:,} customers")
    return _write(rows)


def _sweep(T, rows):
    for n in SIZES:
        print(f"\n=== database with {n:,} customers ===", flush=True)
        T.N_CUSTOMERS = n
        T.main()
        r = subprocess.run(
            [sys.executable, "-u", str(ROOT / "scripts" / "m4_attack.py"),
             "--set", "natural_v2", "--methods", "raw,presidio"],
            cwd=ROOT / "scripts", capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-800:]); continue
        df = pd.read_csv(RESULTS / "m4_attack.csv")
        # the pre-registered configuration, whatever it selected at this size
        best = df[df.method == "raw"].sort_values("U_unique_pct", ascending=False).iloc[0]
        sub = df[(df.fields == best.fields) & (df.amount_tol == best.amount_tol) &
                 (df.date_tol_days == best.date_tol_days)]
        for _, x in sub.iterrows():
            rows.append({"customers": n, "method": x["method"],
                         "U_unique_pct": x["U_unique_pct"], "K_smallset_pct": x["K_smallset_pct"],
                         "R_rank1_pct": x["R_rank1_pct"], "attacker_fp_pct": x["attacker_fp_pct"]})
            print(f"  {x['method']:<10} U {x['U_unique_pct']:5.1f}%  "
                  f"K {x['K_smallset_pct']:5.1f}%  fp {x['attacker_fp_pct']:4.1f}%", flush=True)

    return rows


def _write(rows):
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "m6_dbsize.csv", index=False)
    L = ["M6 — does re-identification survive a bigger database?", "=" * 66, "",
         "Population is the assumption most likely to be quoted against the",
         "headline. Transactions per customer are held constant, so the only",
         "thing changing is how many people the attacker must tell apart.", "",
         f"  {'customers':>10} {'method':<10} {'U unique':>10} {'K set<5':>10} {'attacker fp':>12}"]
    for _, r in out.iterrows():
        L.append(f"  {r['customers']:>10,} {r['method']:<10} {r['U_unique_pct']:>9.1f}% "
                 f"{r['K_smallset_pct']:>9.1f}% {r['attacker_fp_pct']:>11.1f}%")
    raw = out[out.method == "raw"].sort_values("customers")
    if len(raw) > 1:
        first, last = raw.iloc[0], raw.iloc[-1]
        L += ["", f"raw text: U goes {first['U_unique_pct']:.1f}% -> {last['U_unique_pct']:.1f}% "
                  f"as the database grows {first['customers']:,} -> {last['customers']:,}", ""]
    text = "\n".join(L)
    (RESULTS / "m6_dbsize.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
