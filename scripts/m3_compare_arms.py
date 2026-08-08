"""
M3: authored carriers vs hardened injector, three seeds each, on real prose.

THE COMPARISON THIS EXISTS TO MAKE
----------------------------------
Decision 008 diagnosed the encoder's failure on real prose — 59.7% recall,
ORG_THIRD_PARTY at 0.8% — as learning CARRIER CONTEXTS rather than entity types.
Decision 010 rebuilt the injector on that diagnosis: carriers mined from the
corpus, real entity sites for tier 2, value pools diversified and split, hard
negatives added.

Two arms, identical architecture and hyper-parameters, differing only in training
data:

  authored   the original hand-written carrier templates
  hard       the rebuilt injector

Three seeds each, so the comparison carries a spread instead of resting on n=1 —
which the seed sweep already showed matters, since within-arm variation on
training loss was as large as the between-arm gap that looked like a signal.

WHY BOTH ARMS ARE SCORED ON THE SAME TEST SET
---------------------------------------------
The surrogate transfer test (decision 008) is real CFPB prose with markers
refilled by known surrogates. It contains none of either injector's carriers, so
it is neutral ground. Scoring each arm on its own matching injected set would
measure two different things and call it a comparison.

INFERENCE COST IS MEASURED HERE, ON THE LAPTOP
----------------------------------------------
Per decision 011 training ran on a rented GPU, but "a model that runs on a
laptop" is the claim, so seconds-per-narrative and peak memory are measured on
the M1 and reported from it.

Reads:  models/encoder-{authored,hard}-s*/
        data/interim/creditcard_narratives.parquet
        data/synthetic/{customers,transactions}.parquet
Writes: results/m3_arms.csv
        results/m3_arms.txt
"""

from __future__ import annotations

import argparse
import statistics as st
import time
from pathlib import Path

import pandas as pd
import torch

import m3_evaluate as M3
import m3_transfer_surrogate as TS

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MODELS = ROOT / "models"

TIER = TS.TIER if hasattr(TS, "TIER") else {}


def peak_mem_mb() -> float:
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # macOS reports bytes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=TS.N)
    ap.add_argument("--baselines", action="store_true", default=True)
    args = ap.parse_args()

    from transformers import AutoModelForTokenClassification, AutoTokenizer

    # --- one transfer set, built once, shared by every method ---------------
    print("building surrogate transfer set...", flush=True)
    df = TS.build_set(args.n)
    texts = df["text"].tolist()
    truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df["spans"]]
    unfilled = df["unfilled"].tolist()
    n_spans = sum(len(t) for t in truths)
    print(f"  {len(texts):,} real narratives, {n_spans:,} scored spans\n", flush=True)

    def clean(preds):
        """Drop predictions touching an unfilled marker — unknowable either way."""
        return [[sp for sp in p if not any(sp[0] < ue and us < sp[1] for us, ue in unf)]
                for p, unf in zip(preds, unfilled)]

    rows, report = [], {}

    # --- baselines, once ---------------------------------------------------
    if args.baselines:
        import spacy
        from presidio_analyzer import AnalyzerEngine
        nlp = spacy.load("en_core_web_lg")
        an = AnalyzerEngine()
        for name, fn in [("regex", lambda: M3.predict_regex(texts)),
                         ("spacy", lambda: M3.predict_spacy(texts, nlp)),
                         ("presidio", lambda: M3.predict_presidio(texts, an))]:
            t0 = time.time()
            r = M3.score(truths, clean(fn()), want_category=False)
            r["seconds"] = time.time() - t0
            report[name] = [r]
            print(f"  {name:<10} recall {100*r['recall']:5.1f}%  "
                  f"precision {100*r['precision']:5.1f}%  f1 {100*r['f1']:5.1f}%", flush=True)

    # --- every trained model ----------------------------------------------
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"\nencoders on {dev} (this is the hardware the claim is about)\n", flush=True)

    for arm in ("authored", "hard"):
        dirs = sorted(MODELS.glob(f"encoder-{arm}-s*"))
        if not dirs:
            continue
        report[arm] = []
        for d in dirs:
            tok = AutoTokenizer.from_pretrained(d)
            mod = AutoModelForTokenClassification.from_pretrained(d, dtype=torch.float32).to(dev).eval()
            t0 = time.time()
            preds = M3.predict_encoder(texts, mod, tok, dev)
            secs = time.time() - t0
            r = M3.score(truths, clean(preds), want_category=True)
            r["seconds"] = secs
            r["ms_per_narrative"] = 1000 * secs / max(len(texts), 1)
            r["seed"] = d.name.split("-s")[-1]
            report[arm].append(r)
            print(f"  {arm:<9} seed {r['seed']}  recall {100*r['recall']:5.1f}%  "
                  f"precision {100*r['precision']:5.1f}%  f1 {100*r['f1']:5.1f}%  "
                  f"cat {100*(r['cat_acc'] or 0):5.1f}%  {r['ms_per_narrative']:.0f}ms/narr", flush=True)
            del mod

    # --- aggregate ---------------------------------------------------------
    def agg(vals):
        if len(vals) == 1:
            return vals[0], 0.0
        return st.mean(vals), st.stdev(vals)

    L = ["M3 — authored carriers vs hardened injector, on real prose", "=" * 76, "",
         f"{len(texts):,} real CFPB narratives, {n_spans:,} scored spans.",
         "Surrogate-filled (decision 008): real text, real redaction sites, values",
         "we chose. Contains NO carrier templates from either injector, so it is",
         "neutral ground for both arms.", "",
         "Three seeds per arm. Identical architecture and hyper-parameters — the",
         "ONLY difference is the training data (decision 010).", "",
         "-" * 76, "HEADLINE", "",
         f"  {'method':<20} {'recall':>14} {'precision':>14} {'f1':>14} {'cat acc':>9}"]

    for name in ("regex", "spacy", "presidio", "authored", "hard"):
        if name not in report:
            continue
        runs = report[name]
        rm, rs = agg([x["recall"] for x in runs])
        pm, ps = agg([x["precision"] for x in runs])
        fm, fs = agg([x["f1"] for x in runs])
        cm, _ = agg([x["cat_acc"] or 0 for x in runs])
        label = {"authored": "encoder (authored)", "hard": "encoder (HARDENED)"}.get(name, name)

        def cell(m, sd):
            return f"{100*m:5.1f}% ±{100*sd:4.1f}" if len(runs) > 1 else f"{100*m:5.1f}%       "

        cat_cell = f"{100*cm:.1f}%" if cm else "n/a"
        L.append(f"  {label:<20} {cell(rm, rs):>14} {cell(pm, ps):>14} "
                 f"{cell(fm, fs):>14} {cat_cell:>9}")
        for x in runs:
            rows.append({"method": label, "seed": x.get("seed", ""), "category": "ALL",
                         "recall_pct": round(100*x["recall"], 2),
                         "precision_pct": round(100*x["precision"], 2),
                         "f1_pct": round(100*x["f1"], 2),
                         "category_accuracy_pct": round(100*x["cat_acc"], 2) if x["cat_acc"] else "",
                         "tp": x["tp"], "fp": x["fp"], "fn": x["fn"],
                         "ms_per_narrative": round(x.get("ms_per_narrative", 0), 1)})

    # --- the categories the project exists for -----------------------------
    cats = sorted({c for runs in report.values() for r in runs for c in r["per_cat"]},
                  key=lambda c: (TS.TIER.get(c, 9) if hasattr(TS, "TIER") else 9, c))
    L += ["", "-" * 76, "PER-CATEGORY RECALL  (mean across seeds, ± spread)", "",
          f"  {'category':<18} {'n':>6} {'presidio':>10} {'spacy':>10} "
          f"{'authored':>15} {'HARDENED':>15}  {'delta':>8}"]
    for cat in cats:
        n = max((r["per_cat"].get(cat, [0, 0])[1] for runs in report.values() for r in runs),
                default=0)
        if n == 0:
            continue

        def cat_mean(name):
            if name not in report:
                return None, None
            v = [r["per_cat"].get(cat, [0, 0])[0] / max(r["per_cat"].get(cat, [0, 1])[1], 1)
                 for r in report[name] if cat in r["per_cat"]]
            return agg(v) if v else (None, None)

        pres, _ = cat_mean("presidio")
        spac, _ = cat_mean("spacy")
        am, asd = cat_mean("authored")
        hm, hsd = cat_mean("hard")
        delta = (hm - am) if (hm is not None and am is not None) else None
        L.append(
            f"  {cat:<18} {n:>6,} "
            f"{100*pres if pres is not None else 0:>9.1f}% "
            f"{100*spac if spac is not None else 0:>9.1f}% "
            f"{f'{100*am:5.1f} ±{100*asd:4.1f}' if am is not None else '-':>15} "
            f"{f'{100*hm:5.1f} ±{100*hsd:4.1f}' if hm is not None else '-':>15} "
            f"{f'{100*delta:+7.1f}' if delta is not None else '-':>8}")
        for name, key in (("authored", "authored"), ("hard", "hard")):
            for r in report.get(key, []):
                h, t = r["per_cat"].get(cat, [0, 0])
                rows.append({"method": f"encoder ({name})", "seed": r.get("seed", ""),
                             "category": cat, "recall_pct": round(100*h/max(t, 1), 2),
                             "precision_pct": "", "f1_pct": "", "category_accuracy_pct": "",
                             "tp": h, "fp": "", "fn": t-h, "ms_per_narrative": ""})

    # --- inference cost, on the laptop -------------------------------------
    L += ["", "-" * 76, "INFERENCE COST ON THE M1  (this is the claim, decision 011)", ""]
    for arm in ("authored", "hard"):
        if arm in report:
            ms, _ = agg([r["ms_per_narrative"] for r in report[arm]])
            L.append(f"  encoder ({arm:<8})  {ms:6.0f} ms/narrative   "
                     f"{1000/ms:5.1f} narratives/sec")
    size = sum(f.stat().st_size for f in (MODELS / "encoder-hard-s20260806").rglob("*")
               if f.is_file()) / 1e6 if (MODELS / "encoder-hard-s20260806").exists() else 0
    L += [f"  model on disk       {size:6.0f} MB  (fp32; fp16 export would be ~{size/2:.0f} MB)",
          f"  peak process memory {peak_mem_mb():6.0f} MB"]

    out = "\n".join(L)
    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m3_arms.csv", index=False)
    (RESULTS / "m3_arms.txt").write_text(out + "\n")
    print("\n" + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
