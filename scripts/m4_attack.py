"""
M4: the attack. This is the headline, and everything before it was setup.

Take a redacted narrative. Try to find the one customer in the transaction
database that it belongs to. Report how often that succeeds, for each redaction
method.

HOW THE ADVERSARY WORKS (decision 005)
--------------------------------------
Exact matching is fuzzy matching with zero tolerance, so this is not two rival
attackers. It is ONE attacker described by two arguments — which fields it uses,
and how much slack it allows — and M4 sweeps both and publishes the surface.

    extract   pull amounts, dates, merchants, cities and names out of whatever
              survived redaction. Attacker-side only; it never sees our spans.
    match     query the database with tolerance (amount +/- a, date +/- d days)
    score     U / K / R per decision 001, plus the attacker's own error rate

THE PRE-REGISTERED SELECTION RULE, WHICH MATTERS MORE THAN THE SWEEP
--------------------------------------------------------------------
A tolerance sweep is an obvious way to manufacture a headline: loosen until
Presidio-redacted text leaks a lot, tighten until Airlock-redacted text leaks
little, report the gap. That would be fraud dressed as a parameter choice.

So, fixed in decision 005 BEFORE this file was written:

  1. tolerance and field set are chosen on RAW text only — the condition where
     no redaction method is involved and therefore none can be favoured
  2. selection maximises true re-identification subject to the attacker's
     false-positive rate staying under 5%
  3. that ONE configuration is then applied unchanged to every method
  4. the whole sweep is published anyway, so the headline can be located on the
     surface rather than taken on trust

RANK-1 (R), OPERATIONALISED
---------------------------
DEFINITIONS.md defines R as the correct customer ranking first when all
customers are scored. Scoring all 10,000 customers per narrative per
configuration is not affordable, so R is computed over the candidate set,
ranking by number of corroborating transactions. A narrative with no candidates
cannot satisfy R. This is stated because it makes R slightly conservative
relative to its definition, and that is the safe direction.

Reads:  data/synthetic/injected_natural.parquet   (headline set, decision 004)
        data/synthetic/{customers,transactions}.parquet
        models/airlock-encoder/                    (optional)
Writes: results/m4_attack.csv
        results/m4_attack.txt
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"
MODEL_DIR = ROOT / "models" / "airlock-encoder"

SEED = 20260806
PLACEHOLDER = "[REDACTED]"
FP_CEILING = 0.05          # pre-registered, decision 005
K_SMALL = 5                # DEFINITIONS.md: candidate set smaller than 5

AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*\.\d{2})")
DATE_RES = [
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"),
]

# tolerance grid: (amount_dollars, date_days)
TOLERANCES = [(0.0, 0), (0.0, 1), (0.0, 3), (0.0, 7), (1.0, 3), (5.0, 3), (25.0, 7)]
FIELD_SETS = ["amount", "amount+date", "amount+date+merchant", "amount+date+merchant+city"]


# --- extraction (attacker side) --------------------------------------------

NAME_RE = re.compile(r"\b[A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,15}\b")


def extract(text: str, merchant_names: list[str], city_names: list[str],
            name_set: set[str]) -> dict:
    """
    Everything the attacker can pull out of surviving text. It holds the
    database, so it can recognise known merchant, city and customer names —
    that is what makes an attacker an attacker rather than a parser.

    Names are found by pulling capitalised bigrams out of the text and looking
    them up, NOT by scanning all 10,000 customers per narrative. The scanning
    version was 40 million substring searches and dominated the entire run.
    """
    amounts = [float(a.replace(",", "")) for a in AMOUNT_RE.findall(text)]
    dates = []
    for rx in DATE_RES:
        for m, d, y in rx.findall(text):
            try:
                yr = int(y) if len(y) == 4 else 2000 + int(y)
                dates.append(date(yr, int(m), int(d)).toordinal())
            except ValueError:
                continue
    low = text.lower()
    merchants = [m for m in merchant_names if m.lower() in low]
    cities = [c for c in city_names if c.lower() in low]
    names = [c for c in NAME_RE.findall(text) if c in name_set]
    return {"amounts": amounts, "dates": dates, "merchants": merchants,
            "cities": cities, "names": names}


# --- redaction --------------------------------------------------------------

def redact(text: str, spans) -> str:
    """Replace predicted spans with a placeholder, right to left."""
    out = text
    for s, e, *_ in sorted(spans, key=lambda x: -x[0]):
        out = out[:s] + PLACEHOLDER + out[e:]
    return out


# --- the database index -----------------------------------------------------

class Index:
    """
    Transaction index supporting queries from ANY available field.

    The first version required a dollar amount and returned nothing without one.
    That made the regex baseline score 0.0% — apparently a perfect redactor,
    actually just a redactor that destroys the attacker's only entry point. An
    attacker that gives up without an amount measures one field, not the leak.
    So amount is now one field among several (decision 007).
    """

    def __init__(self, tdf: pd.DataFrame, cdf: pd.DataFrame):
        t = tdf.reset_index(drop=True)
        self.amount = t["amount"].to_numpy()
        self.date = np.array([date.fromisoformat(d).toordinal() for d in t["txn_date"]])
        self.cust = t["customer_id"].to_numpy()

        self.amt_order = np.argsort(self.amount, kind="stable")
        self.amt_sorted = self.amount[self.amt_order]
        self.date_order = np.argsort(self.date, kind="stable")
        self.date_sorted = self.date[self.date_order]

        self.merchant_lower = t["merchant_name"].str.lower().to_numpy()
        self.by_merchant: dict[str, np.ndarray] = {}
        for name, grp in t.groupby(t["merchant_name"].str.lower()):
            self.by_merchant[name] = grp.index.to_numpy()

        self.cust_city = dict(zip(cdf["customer_id"], cdf["city"].str.lower()))
        self.cust_name = dict(zip(cdf["customer_id"], cdf["full_name"].str.lower()))
        self.by_name: dict[str, list[str]] = {}
        for cid, nm in zip(cdf["customer_id"], cdf["full_name"].str.lower()):
            self.by_name.setdefault(nm, []).append(cid)

    def _amount_band(self, amounts, tol):
        out = []
        for a in amounts[:6]:
            lo = np.searchsorted(self.amt_sorted, a - tol - 1e-9, "left")
            hi = np.searchsorted(self.amt_sorted, a + tol + 1e-9, "right")
            if hi > lo:
                out.append(self.amt_order[lo:hi])
        return np.unique(np.concatenate(out)) if out else np.array([], dtype=int)

    def _date_band(self, dates, tol):
        out = []
        for d in dates[:6]:
            lo = np.searchsorted(self.date_sorted, d - tol, "left")
            hi = np.searchsorted(self.date_sorted, d + tol, "right")
            if hi > lo:
                out.append(self.date_order[lo:hi])
        return np.unique(np.concatenate(out)) if out else np.array([], dtype=int)

    def _merchant_band(self, merchants):
        out = [self.by_merchant[m.lower()] for m in merchants[:6] if m.lower() in self.by_merchant]
        return np.unique(np.concatenate(out)) if out else np.array([], dtype=int)

    def query(self, ex: dict, fields: str, amt_tol: float, day_tol: int) -> dict[str, int]:
        """
        Query from the most selective available field, then filter.

        Selectivity is not a performance trick here, it is the measurement from
        M2: a single date matches 479 customers and a single merchant 1,329, so
        neither can serve as a primary key. Amount (16.3 customers) and merchant
        can open a search; a date can only narrow one. An attacker holding only
        a date has not identified anybody, and returning nothing is the correct
        answer rather than a shortcut.
        """
        idx = None
        if "amount" in fields and ex["amounts"]:
            idx = self._amount_band(ex["amounts"], amt_tol)
        elif "merchant" in fields and ex["merchants"]:
            idx = self._merchant_band(ex["merchants"])

        hits: dict[str, int] = {}
        if idx is not None and len(idx):
            if "date" in fields and ex["dates"]:
                dts = self.date[idx]
                keep = np.zeros(len(idx), dtype=bool)
                for d in ex["dates"][:6]:
                    keep |= np.abs(dts - d) <= day_tol
                idx = idx[keep]
            if "merchant" in fields and ex["merchants"] and "amount" in fields and ex["amounts"]:
                want = {m.lower() for m in ex["merchants"]}
                ms = self.merchant_lower[idx]
                idx = idx[np.isin(ms, list(want))]
            for c in self.cust[idx]:
                hits[c] = hits.get(c, 0) + 1

        # A name alone identifies 85.4% of customers in this database, so an
        # attacker holding one does not need a transaction at all.
        if ex["names"]:
            named: dict[str, int] = {}
            for n in ex["names"][:4]:
                for cid in self.by_name.get(n.lower(), []):
                    named[cid] = named.get(cid, 0) + 1
            if named:
                both = {c: hits.get(c, 0) + v for c, v in named.items() if c in hits}
                hits = both if both else named

        if "city" in fields and ex["cities"] and hits:
            want = {c.lower() for c in ex["cities"]}
            narrowed = {c: n for c, n in hits.items() if self.cust_city.get(c) in want}
            if narrowed:
                hits = narrowed
        return hits


def evaluate(extracted: list[dict], truth: list[str], index: Index,
             fields: str, amt_tol: float, day_tol: int) -> dict:
    u = k = r = fp = attacked = 0
    for ex, gold in zip(extracted, truth):
        attacked += 1
        hits = index.query(ex, fields, amt_tol, day_tol)
        if not hits:
            continue
        cands = list(hits)
        if len(cands) == 1:
            if cands[0] == gold:
                u += 1
            else:
                fp += 1                      # confident, and wrong
        if gold in hits and len(cands) < K_SMALL:
            k += 1
        best = max(hits.items(), key=lambda kv: kv[1])[1]
        top = [c for c, n in hits.items() if n == best]
        if len(top) == 1 and top[0] == gold:
            r += 1
    n = max(attacked, 1)
    return {"U": u / n, "K": k / n, "R": r / n, "FP": fp / n, "attacked": attacked}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="raw,regex,spacy,presidio,encoder")
    ap.add_argument("--set", default="natural_v2", help="natural (marker-derived) or natural_v2 (decision 007)")
    args = ap.parse_args()

    inj = pd.read_parquet(SYN / f"injected_{args.set}.parquet")
    cdf = pd.read_parquet(SYN / "customers.parquet")
    tdf = pd.read_parquet(SYN / "transactions.parquet")
    texts = inj["text"].tolist()
    truth = inj["customer_id"].tolist()

    merchant_names = sorted(tdf["merchant_name"].unique().tolist())
    city_names = sorted(cdf["city"].unique().tolist())
    name_set = set(cdf["full_name"].tolist())
    index = Index(tdf, cdf)

    # --- produce redacted text per method ---------------------------------
    import m3_evaluate as M3
    methods = [m for m in args.methods.split(",")]
    variants: dict[str, list[str]] = {}

    for m in methods:
        t0 = time.time()
        if m == "raw":
            variants["raw"] = texts
        elif m == "regex":
            variants[m] = [redact(t, p) for t, p in zip(texts, M3.predict_regex(texts))]
        elif m == "spacy":
            import spacy
            nlp = spacy.load("en_core_web_lg")
            variants[m] = [redact(t, p) for t, p in zip(texts, M3.predict_spacy(texts, nlp))]
        elif m == "presidio":
            from presidio_analyzer import AnalyzerEngine
            an = AnalyzerEngine()
            variants[m] = [redact(t, p) for t, p in zip(texts, M3.predict_presidio(texts, an))]
        elif m == "encoder":
            if not MODEL_DIR.exists():
                print("  (encoder not trained yet — skipping that row)")
                continue
            import torch
            from transformers import AutoModelForTokenClassification, AutoTokenizer
            dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
            tok = AutoTokenizer.from_pretrained(MODEL_DIR)
            mod = AutoModelForTokenClassification.from_pretrained(
                MODEL_DIR, dtype=torch.float32).to(dev).eval()
            variants[m] = [redact(t, p) for t, p in zip(texts, M3.predict_encoder(texts, mod, tok, dev))]
        print(f"  redacted with {m:<9} ({time.time()-t0:.0f}s)", flush=True)

    # --- extract once per method, then sweep ------------------------------
    extracted = {m: [extract(t, merchant_names, city_names, name_set) for t in v]
                 for m, v in variants.items()}

    rows = []
    for m, ex in extracted.items():
        for fields in FIELD_SETS:
            for amt_tol, day_tol in TOLERANCES:
                res = evaluate(ex, truth, index, fields, amt_tol, day_tol)
                rows.append({"method": m, "fields": fields, "amount_tol": amt_tol,
                             "date_tol_days": day_tol,
                             "U_unique_pct": round(100*res["U"], 2),
                             "K_smallset_pct": round(100*res["K"], 2),
                             "R_rank1_pct": round(100*res["R"], 2),
                             "attacker_fp_pct": round(100*res["FP"], 2),
                             "narratives_attacked": res["attacked"]})
        print(f"  swept {m}", flush=True)

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "m4_attack.csv", index=False)

    # --- PRE-REGISTERED SELECTION, on raw text only -----------------------
    raw = df[(df["method"] == "raw") & (df["attacker_fp_pct"] <= 100 * FP_CEILING)]
    if raw.empty:
        raw = df[df["method"] == "raw"].nsmallest(1, "attacker_fp_pct")
    best = raw.sort_values("U_unique_pct", ascending=False).iloc[0]
    cfg = (best["fields"], best["amount_tol"], best["date_tol_days"])
    head = df[(df["fields"] == cfg[0]) & (df["amount_tol"] == cfg[1]) &
              (df["date_tol_days"] == cfg[2])]

    L = ["M4 — the attack", "=" * 72, "",
         f"set: injected_{args.set} ({len(texts):,} narratives)",
         f"database: {len(cdf):,} customers, {len(tdf):,} transactions", "",
         "PRE-REGISTERED CONFIGURATION (decision 005)", "-" * 72,
         "Chosen on RAW text only, maximising unique re-identification subject",
         f"to attacker false-positive rate <= {100*FP_CEILING:.0f}%. Applied unchanged to every",
         "redaction method. The full sweep is below so the headline can be",
         "located on the surface rather than taken on trust.", "",
         f"  fields          {cfg[0]}",
         f"  amount tolerance  +/- ${cfg[1]:.2f}",
         f"  date tolerance    +/- {int(cfg[2])} days", "",
         "-" * 72, "HEADLINE — re-identification rate at that configuration", "",
         f"  {'method':<12} {'U unique':>10} {'K set<5':>10} {'R rank-1':>10} {'attacker FP':>12}"]
    for _, r in head.iterrows():
        L.append(f"  {r['method']:<12} {r['U_unique_pct']:>9.1f}% {r['K_smallset_pct']:>9.1f}% "
                 f"{r['R_rank1_pct']:>9.1f}% {r['attacker_fp_pct']:>11.1f}%")
    L += ["", "  U is the headline (DEFINITIONS.md): most conservative, smallest",
          "  rate, weakest claim about risk. K and R sit beside it, not beneath.", ""]

    L += ["-" * 72, "THE SURFACE — U by tolerance, all field sets", ""]
    for fields in FIELD_SETS:
        L.append(f"  fields = {fields}")
        L.append(f"    {'method':<12}" + "".join(
            f"{f'${a:g}/{d}d':>11}" for a, d in TOLERANCES))
        for m in variants:
            cells = ""
            for a, d in TOLERANCES:
                v = df[(df["method"] == m) & (df["fields"] == fields) &
                       (df["amount_tol"] == a) & (df["date_tol_days"] == d)]
                cells += f"{v.iloc[0]['U_unique_pct']:>10.1f}%" if len(v) else f"{'-':>11}"
            L.append(f"    {m:<12}" + cells)
        L.append("")

    L += ["-" * 72, "STABILITY (decision 001)", "",
          "How far U moves across the sweep. A definition that swings wildly is",
          "measuring the attacker's tuning rather than the leak.", "",
          f"  {'method':<12} {'min U':>9} {'max U':>9} {'spread':>9}"]
    for m in variants:
        s = df[df["method"] == m]["U_unique_pct"]
        L.append(f"  {m:<12} {s.min():>8.1f}% {s.max():>8.1f}% {s.max()-s.min():>8.1f}")

    if "encoder" not in variants:
        L += ["", "NOTE: the encoder row is absent because M3 has not finished",
              "training. Every other row is final and will not be recomputed."]

    out = "\n".join(L)
    (RESULTS / "m4_attack.txt").write_text(out + "\n")
    print("\n" + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
