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
SIZES = [2_500, 10_000, 40_000]


def main() -> int:
    import m2_transactions as T

    rows = []
    original = T.N_CUSTOMERS
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

    T.N_CUSTOMERS = original
    T.main()  # restore the canonical database so nothing downstream is surprised

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
