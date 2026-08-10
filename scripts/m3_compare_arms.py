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

WHERE THIS RUNS
---------------
Accuracy is hardware-independent — same weights, same fp32 inference, same
argmax — so it runs wherever is fastest. Throughput and cost are a DIFFERENT
measurement and live in m3_throughput.py, which runs on the GPU because that is
where a deployed redactor runs (decision 012).

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
    """Peak RSS in MB.

    ru_maxrss is in BYTES on macOS and KILOBYTES on Linux. Assuming bytes
    everywhere under-reported a run on the Linux GPU box by 1000x, and it was
    published as "peak process memory 7 MB" for a job holding several GB.
    """
    import resource
    import sys as _sys
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 1e6 if _sys.platform == "darwin" else raw / 1e3


ARM_LABEL = {"micro": "encoder micro 70.7M", "base2": "encoder base 184M",
             "large": "encoder large 434M", "writer": "writer Qwen3 0.6B",
             "regex": "regex", "spacy": "spacy", "presidio": "presidio"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=TS.N)
    ap.add_argument("--baselines", action="store_true", default=True)
    ap.add_argument("--no-baselines", dest="baselines", action="store_false")
    ap.add_argument("--arms", default="micro,base2,large")
    ap.add_argument("--writer", default="", help="path to a generative model to include")
    ap.add_argument("--writer-batch", type=int, default=8,
                    help="generation batch size; safe to raise once length-bucketed")
    ap.add_argument("--no-bucket", action="store_true",
                    help="disable length-bucketing (for diffing against the old path)")
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

    ARMS = tuple(a for a in args.arms.split(",") if a)
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
    # CUDA first. This script was written when the M1 was the only target and
    # silently fell back to CPU on a rented GPU — the eval ran with the card at
    # 0% utilisation. Accuracy is hardware-independent so the numbers would have
    # been right, but it would have taken hours on a box billing by the hour.
    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"\nrunning on {dev}\n", flush=True)

    for arm in ARMS:
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

    # --- the writer, if one was given -------------------------------------
    if args.writer:
        import m3_predict_generative as GEN
        from m3_train_generative import INSTRUCTION
        from peft import PeftModel
        from transformers import AutoModelForCausalLM
        wdir = Path(args.writer)
        wtok = AutoTokenizer.from_pretrained(wdir)
        if wtok.pad_token is None:
            wtok.pad_token = wtok.eos_token
        cfg = __import__("json").loads((wdir / "checkpoint.json").read_text())
        base = AutoModelForCausalLM.from_pretrained(cfg["base_model"], dtype=torch.float32).to(dev)
        wmod = PeftModel.from_pretrained(base, wdir).to(dev).eval()
        t0 = time.time()
        wpreds, wstats = GEN.predict(texts, wmod, wtok, dev, INSTRUCTION,
                                     batch=args.writer_batch,
                                     bucket=not args.no_bucket,
                                     progress_every=100)
        r = M3.score(truths, clean(wpreds), want_category=True)
        r["seconds"] = time.time() - t0
        r["ms_per_narrative"] = 1000 * r["seconds"] / max(len(texts), 1)
        r["seed"] = wdir.name.split("-s")[-1]
        r["drift"] = wstats
        report["writer"] = [r]
        print(f"  writer    recall {100*r['recall']:5.1f}%  precision {100*r['precision']:5.1f}%  "
              f"f1 {100*r['f1']:5.1f}%  | drift {100*wstats['drift_rate']:.1f}%  "
              f"unparseable {100*wstats['unparseable_rate']:.1f}%", flush=True)

    for name in ("regex", "spacy", "presidio", *ARMS, "writer"):
        if name not in report:
            continue
        runs = report[name]
        rm, rs = agg([x["recall"] for x in runs])
        pm, ps = agg([x["precision"] for x in runs])
        fm, fs = agg([x["f1"] for x in runs])
        cm, _ = agg([x["cat_acc"] or 0 for x in runs])
        # 70.7M, not 22M: deberta-v3-xsmall has a 22M backbone and a 128k-vocab
        # embedding table on top. Both figures are real, but the throughput table
        # and the README quote the total, so this one has to as well.
        label = ARM_LABEL.get(name, name)

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
    if "writer" in report and report["writer"][0].get("drift"):
        d = report["writer"][0]["drift"]
        L += ["", "-" * 76, "WRITER TEXT DRIFT  (decision 006: reported, never repaired)", "",
              f"  narratives where untagged text was altered   {100*d['drift_rate']:5.1f}%",
              f"  output too mangled to align at all           {100*d['unparseable_rate']:5.1f}%",
              f"  share of characters differing from input     {100*d['drift_char_share']:5.2f}%", "",
              "  A drifted narrative contributes NO spans. In deployment you ship the",
              "  writer's OUTPUT, so if that text differs from the input it is not a",
              "  redaction of the input and cannot be credited as one.", ""]

    cats = sorted({c for runs in report.values() for r in runs for c in r["per_cat"]},
                  key=lambda c: (TS.TIER.get(c, 9) if hasattr(TS, "TIER") else 9, c))

    # Columns are whatever actually ran. This table used to be hardcoded to the
    # arms named "authored" and "HARDENED", which have not existed since the
    # four-arm comparison replaced them -- so every cell rendered from a missing
    # key, and a method that was never run printed as "0.0%" rather than as
    # absent. A method that was not measured must never render as a number.
    cat_methods = [m for m in ("regex", "spacy", "presidio") if m in report] + \
                  [a for a in ARMS if a in report]
    L += ["", "-" * 76, "PER-CATEGORY RECALL  (mean across seeds, ± spread)", ""]
    if not any(m in report for m in ("regex", "spacy", "presidio")):
        L += ["  Baselines were not run (--no-baselines); their columns are omitted",
              "  rather than shown as zero. Run without that flag to compare.", ""]
    L.append(f"  {'category':<18} {'n':>6}" + "".join(f"{ARM_LABEL.get(m, m):>21}"
                                                      for m in cat_methods))

    def cat_mean(name, cat):
        if name not in report:
            return None, None
        v = [r["per_cat"].get(cat, [0, 0])[0] / max(r["per_cat"].get(cat, [0, 1])[1], 1)
             for r in report[name] if cat in r["per_cat"]]
        return agg(v) if v else (None, None)

    for cat in cats:
        n = max((r["per_cat"].get(cat, [0, 0])[1] for runs in report.values() for r in runs),
                default=0)
        if n == 0:
            continue
        cells = ""
        for m in cat_methods:
            mu, sd = cat_mean(m, cat)
            if mu is None:
                cells += f"{'not run':>21}"
            elif len(report[m]) > 1:
                cells += f"{f'{100*mu:5.1f} ±{100*sd:4.1f}':>21}"
            else:
                cells += f"{f'{100*mu:5.1f}':>21}"
        L.append(f"  {cat:<18} {n:>6,}" + cells)
        for m in cat_methods:
            for r in report.get(m, []):
                h, t = r["per_cat"].get(cat, [0, 0])
                if t == 0:
                    continue
                rows.append({"method": ARM_LABEL.get(m, m), "seed": r.get("seed", ""),
                             "category": cat, "recall_pct": round(100*h/max(t, 1), 2),
                             "precision_pct": "", "f1_pct": "", "category_accuracy_pct": "",
                             "tp": h, "fp": "", "fn": t-h, "ms_per_narrative": ""})

    # --- inference cost, and where it was actually measured ----------------
    # Decision 011 requires the latency claim to be measured on the M1. This
    # block used to assert that in its heading regardless of the hardware it ran
    # on, and it published "0 MB / 7 MB" from a run on a rented GPU -- 0 because
    # it sized a model directory that no longer exists, 7 because ru_maxrss is
    # kilobytes on Linux. It now names the device and refuses the M1 claim when
    # it is not on one.
    on_m1 = dev.type == "mps"
    heading = ("INFERENCE COST ON THE M1  (this is the claim, decision 011)" if on_m1
               else f"INFERENCE COST on {dev.type.upper()}  — NOT the M1 claim")
    L += ["", "-" * 76, heading, ""]
    if not on_m1:
        L += ["  Decision 011 requires the published latency to come from the M1.",
              "  These figures were measured elsewhere and are indicative only;",
              "  re-run this on the laptop before quoting them.", ""]
    for arm in ARMS:
        if arm not in report:
            continue
        ms, _ = agg([r["ms_per_narrative"] for r in report[arm]])
        d = sorted(MODELS.glob(f"encoder-{arm}-s*"))
        size = (sum(f.stat().st_size for f in d[0].rglob("*") if f.is_file()) / 1e6
                if d else 0.0)
        size_cell = f"{size:6.0f} MB" if size else "     ?"
        L.append(f"  {ARM_LABEL.get(arm, arm):<22} {ms:6.0f} ms/narrative   "
                 f"{1000/ms:6.1f} narr/sec   on disk {size_cell}")
    L += ["", f"  peak process memory   {peak_mem_mb():6.0f} MB",
          "  (fp32 on disk; an fp16 export would be about half)"]

    out = "\n".join(L)
    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m3_arms.csv", index=False)
    (RESULTS / "m3_arms.txt").write_text(out + "\n")
    print("\n" + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
