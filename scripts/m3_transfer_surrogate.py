"""
M3: a transfer test that is actually valid.

WHY THE FIRST TRANSFER TEST WAS WRONG
-------------------------------------
The first attempt scored every method on real CFPB narratives against the XXXX
markers. The encoder got 0.9%; Presidio got 60.7%; spaCy got 68.5%. Read quickly,
that says the encoder does not transfer.

It says nothing of the kind. In published CFPB text the personal information has
ALREADY BEEN REMOVED and replaced by XXXX. There is no name left to find. To
score against those markers a method has to flag the marker itself — and flagging
XXXX is exactly the degenerate "XXXX -> redact" behaviour that M1 established
must never be learned.

The encoder predicted 260 spans across 3,000 narratives, because it was trained
on text where personal information has real surface forms and it correctly
ignores a token that carries none. Presidio and spaCy score well because spaCy's
NER tags a capitalised XXXX as an entity from context.

So that metric rewards the shortcut and punishes correct behaviour. It cannot
answer the question decision 006 asked.

WHAT THIS SCRIPT DOES INSTEAD
-----------------------------
Real prose, real redaction sites, realistic surface forms:

  1. take real marked narratives
  2. estimate each marker's category from surviving context
  3. replace the marker with a plausible SURROGATE of that category, drawn from
     a synthetic customer — "XXXX" becomes "Sarah Mendez" or "$47.13"
  4. record exact positions while doing so, single forward pass
  5. score every method on those positions

The result is text a human wrote, redacted where a human decided personal
information was, refilled with values whose positions we know exactly. Crucially
it contains NONE of the injector's carrier templates, so nothing a method scores
here can be explained by template memorisation.

TWO LIMITATIONS, BOTH REPORTED RATHER THAN HIDDEN
-------------------------------------------------
1. Only markers whose category can be estimated from context are filled — about
   46.5% of them (decision 004). The rest stay as XXXX and are NEVER scored, for
   or against anyone.
2. Predictions overlapping an unfilled marker are excluded from the
   false-positive count. A method flagging a leftover XXXX is neither right nor
   wrong here, since we do not know what was there, and counting it either way
   would punish or reward the marker shortcut all over again.

Reads:  data/interim/creditcard_narratives.parquet
        data/synthetic/customers.parquet, transactions.parquet
Writes: data/synthetic/transfer_surrogate.parquet
        results/m3_transfer.csv
        results/m3_transfer.txt
"""

from __future__ import annotations

import argparse
import random
import re
import time
from pathlib import Path

import pandas as pd

from m2_category_distribution import MARKER_SPAN, classify
from m2_inject import TIER, resolve

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"
NARRATIVES = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
MODEL_DIR = ROOT / "models" / "airlock-encoder"

SEED = 20260806
N = 3_000

# Which generated field stands in for each estimated marker category.
SURROGATE_FIELD = {
    "PERSON": "person_full", "ACCOUNT_ID": "last4", "GOV_ID": "ssn",
    "CONTACT": "phone", "CASE_REF": "case_ref", "RELATIONSHIP": "relationship",
    "LOCATION_FINE": "city", "EMPLOYER": "employer", "LIFE_EVENT": "life_event",
    "PROTECTED_ATTR": "protected", "HEALTH": "health",
    "ORG_THIRD_PARTY": "bank", "AMOUNT": "amount", "DATE": "date",
    "MERCHANT": "merchant", "TEMPORAL": "weekday",
}


def build_set(n: int) -> pd.DataFrame:
    rng = random.Random(SEED)
    df = pd.read_parquet(NARRATIVES, columns=["narrative"])
    marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
    marked = marked.drop_duplicates(subset="narrative")
    texts = marked.sample(n=min(n, len(marked)), random_state=SEED)["narrative"].tolist()

    customers = pd.read_parquet(SYN / "customers.parquet").to_dict("records")
    tdf = pd.read_parquet(SYN / "transactions.parquet")
    txn_by_cust: dict[str, list[dict]] = {}
    for r in tdf.to_dict("records"):
        txn_by_cust.setdefault(r["customer_id"], []).append(r)

    rows = []
    for i, text in enumerate(texts):
        cust = customers[i % len(customers)]
        txns = txn_by_cust.get(cust["customer_id"])
        if not txns:
            continue
        txn = dict(rng.choice(txns))
        txn["last4"] = f"{rng.randint(0, 9999):04d}"

        out: list[str] = []
        spans: list[dict] = []
        unfilled: list[tuple[int, int]] = []
        pos = 0
        last = 0

        for m in MARKER_SPAN.finditer(text):
            cat = classify(text, m.start(), m.end())
            literal = text[last : m.start()]
            out.append(literal)
            pos += len(literal)

            if cat in SURROGATE_FIELD:
                value = resolve(SURROGATE_FIELD[cat], cust, txn, rng)
                spans.append({"start": pos, "end": pos + len(value),
                              "category": cat, "tier": TIER[cat], "value": value})
                out.append(value)
                pos += len(value)
            else:
                # Not estimable, or estimated NOT_PII. Left as-is and never scored.
                marker = text[m.start() : m.end()]
                unfilled.append((pos, pos + len(marker)))
                out.append(marker)
                pos += len(marker)
            last = m.end()

        out.append(text[last:])
        new_text = "".join(out)
        for s in spans:
            assert new_text[s["start"] : s["end"]] == s["value"], "offset drift"
        if spans:
            rows.append({"doc_id": f"transfer-{i:05d}", "customer_id": cust["customer_id"],
                         "txn_id": txn["txn_id"], "text": new_text, "spans": spans,
                         "unfilled": unfilled, "n_spans": len(spans)})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=N)
    ap.add_argument("--methods", default="encoder,presidio,spacy,regex")
    args = ap.parse_args()

    import m3_evaluate as M3

    df = build_set(args.n)
    df.to_parquet(SYN / "transfer_surrogate.parquet", index=False)
    texts = df["text"].tolist()
    truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df["spans"]]
    unfilled = df["unfilled"].tolist()
    n_spans = sum(len(t) for t in truths)
    print(f"transfer set: {len(texts):,} real narratives, {n_spans:,} surrogate spans\n", flush=True)

    methods = args.methods.split(",")
    nlp = analyzer = model = tok = dev = None
    if "spacy" in methods:
        import spacy
        nlp = spacy.load("en_core_web_lg")
    if "presidio" in methods:
        from presidio_analyzer import AnalyzerEngine
        analyzer = AnalyzerEngine()
    if "encoder" in methods:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
        dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        tok = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForTokenClassification.from_pretrained(
            MODEL_DIR, dtype=torch.float32).to(dev).eval()

    rows, report = [], {}
    for m in methods:
        t0 = time.time()
        if m == "regex":
            preds = M3.predict_regex(texts)
        elif m == "spacy":
            preds = M3.predict_spacy(texts, nlp)
        elif m == "presidio":
            preds = M3.predict_presidio(texts, analyzer)
        else:
            preds = M3.predict_encoder(texts, model, tok, dev)
        secs = time.time() - t0

        # Drop predictions that touch an unfilled marker: we do not know what was
        # there, so they are neither right nor wrong.
        cleaned = []
        for p, unf in zip(preds, unfilled):
            cleaned.append([sp for sp in p
                            if not any(sp[0] < ue and us < sp[1] for us, ue in unf)])
        r = M3.score(truths, cleaned, want_category=(m == "encoder"))
        r["seconds"] = secs
        report[m] = r
        print(f"  {m:<10} recall {100*r['recall']:5.1f}%  precision {100*r['precision']:5.1f}%"
              f"  f1 {100*r['f1']:5.1f}%  ({secs:.0f}s)", flush=True)
        rows.append({"method": m, "category": "ALL",
                     "recall_pct": round(100*r["recall"], 2),
                     "precision_pct": round(100*r["precision"], 2),
                     "f1_pct": round(100*r["f1"], 2),
                     "category_accuracy_pct": round(100*r["cat_acc"], 2) if r["cat_acc"] else "",
                     "tp": r["tp"], "fp": r["fp"], "fn": r["fn"]})
        for cat, (h, tot) in sorted(r["per_cat"].items()):
            rows.append({"method": m, "category": cat, "recall_pct": round(100*h/max(tot, 1), 2),
                         "precision_pct": "", "f1_pct": "", "category_accuracy_pct": "",
                         "tp": h, "fp": "", "fn": tot-h})

    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m3_transfer.csv", index=False)

    L = ["M3 — transfer to real prose (surrogate-filled)", "=" * 70, "",
         f"{len(texts):,} real CFPB narratives, {n_spans:,} scored spans", "",
         "Real text a human wrote, redacted where a human decided personal",
         "information was, refilled with values whose positions we recorded.",
         "Contains NONE of the injector's carrier templates, so nothing scored",
         "here can be explained by template memorisation.", "",
         "This REPLACES the earlier marker-based transfer test, which asked",
         "methods to flag XXXX itself and therefore rewarded exactly the",
         "degenerate behaviour M1 said must not be learned.", "",
         f"  {'method':<12} {'recall':>8} {'precision':>10} {'f1':>8} {'cat acc':>9}"]
    for m in methods:
        r = report[m]
        ca = f"{100*r['cat_acc']:.1f}%" if r["cat_acc"] else "n/a"
        L.append(f"  {m:<12} {100*r['recall']:>7.1f}% {100*r['precision']:>9.1f}% "
                 f"{100*r['f1']:>7.1f}% {ca:>9}")

    L += ["", "-" * 70, "PER-CATEGORY RECALL", "",
          f"  {'category':<18} {'tier':>4} {'n':>7}" + "".join(f"{m:>11}" for m in methods)]
    cats = sorted(report[methods[0]]["per_cat"], key=lambda c: (TIER.get(c, 9), c))
    for cat in cats:
        n = report[methods[0]]["per_cat"][cat][1]
        cells = "".join(
            f"{100*report[m]['per_cat'].get(cat,[0,0])[0]/max(report[m]['per_cat'].get(cat,[0,1])[1],1):>10.1f}%"
            for m in methods)
        L.append(f"  {cat:<18} {TIER.get(cat,''):>4} {n:>7,}{cells}")

    L += ["", "LIMITATIONS", "",
          "  Only markers whose category context can estimate are filled (~46.5%).",
          "  The rest stay XXXX and are never scored, for or against anyone.",
          "  Predictions touching an unfilled marker are dropped from the",
          "  false-positive count, since what was there is unknown.",
          "  Category estimates come from context rules and can be wrong; a",
          "  surrogate filled under the wrong category tests the wrong thing."]
    out = "\n".join(L)
    (RESULTS / "m3_transfer.txt").write_text(out + "\n")
    print("\n" + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
