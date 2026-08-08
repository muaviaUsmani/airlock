"""
M3: score every method on identical data — the comparison M1 could not make.

M1 measured the baselines against the CFPB XXXX markers and hit a wall: on that
substrate a regex scores 0.0% BY CONSTRUCTION, because a card-number pattern
looks for digits and a marker is the letter X. A whole class of method could not
be scored at all.

Injected data fixes that. Every span has a realistic surface form and an exact
recorded position, so recall, precision AND category accuracy are all measurable,
for every method, on the same text.

WHAT GETS REPORTED, AND WHY EACH ROW EXISTS
-------------------------------------------
  stratified      per-category scores. Equal power per category (decision 004),
                  so tier-2 categories have enough spans to say anything about.
  natural         aggregate scores at measured corpus frequencies.
  seen_templates  THE CONTROL. Same eval narratives as `stratified`, rendered
                  with TRAINING carrier templates. A model that scores well here
                  and badly on `stratified` memorised phrasing rather than
                  learning what personal information looks like. The gap between
                  them is the diagnostic, and it is reported as a headline number
                  rather than buried.
  transfer        real CFPB marked narratives, scored against XXXX markers. No
                  injected templates exist there at all, so performance cannot be
                  explained by template memorisation. Per decision 006 this is
                  the number that matters most.

A NOTE ON PRECISION
-------------------
Precision counts a predicted span as a false positive when it matches no injected
span. That rests on decision 003's assumption that a narrative a CFPB redactor
marked zero times contains no personal information. M1 found the assumption is
not perfect — 5 direct identifiers survived in 15,000 narratives — so precision
here is very slightly understated for every method equally.

Reads:  models/airlock-encoder/
        data/synthetic/injected_{natural,stratified,seen_templates}.parquet
        data/interim/creditcard_narratives.parquet
Writes: results/m3_comparison.csv
        results/m3_comparison.txt
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"
MODEL_DIR = ROOT / "models" / "airlock-encoder"
NARRATIVES = ROOT / "data" / "interim" / "creditcard_narratives.parquet"

SEED = 20260806
TRANSFER_N = 3_000
OVERRUN = 0.5          # DEFINITIONS.md: predicted span may not overrun by >50%
BATCH = 16

MARKER_SPAN = re.compile(
    r"(?<![A-Za-z0-9])X{2,}(?:\s*/\s*(?:X{2,4}|\d{2,4})|[ \t]+X{2,})*(?![A-Za-z0-9])"
)

TIER = {
    "PERSON": 1, "ACCOUNT_ID": 1, "GOV_ID": 1, "CONTACT": 1, "CASE_REF": 1,
    "RELATIONSHIP": 2, "LOCATION_FINE": 2, "EMPLOYER": 2, "LIFE_EVENT": 2,
    "PROTECTED_ATTR": 2, "HEALTH": 2, "ORG_THIRD_PARTY": 2,
    "AMOUNT": 3, "DATE": 3, "MERCHANT": 3, "TEMPORAL": 3,
}

REGEX_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),
    re.compile(r"\bhttps?://\S+\b"),
    re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane)\b"),
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),
    re.compile(r"\$\s?\d[\d,]*\.\d{2}\b"),
]
SPACY_PII_LABELS = {"PERSON", "GPE", "LOC", "ORG", "FAC", "DATE", "NORP", "MONEY", "TIME"}


def merge(spans):
    if not spans:
        return []
    spans = sorted(spans)
    out = [list(spans[0])]
    for s, e, *rest in spans[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e, *rest])
    return [tuple(x) for x in out]


def matches(true, pred) -> bool:
    ts, te = true[0], true[1]
    ps, pe = pred[0], pred[1]
    if not (ps < te and ts < pe):
        return False
    overrun = max(0, ts - ps) + max(0, pe - te)
    return overrun <= OVERRUN * max(te - ts, 1)


# --- predictors ------------------------------------------------------------

def predict_regex(texts):
    return [merge([(m.start(), m.end(), None) for p in REGEX_PATTERNS for m in p.finditer(t)])
            for t in texts]


def predict_spacy(texts, nlp):
    out = []
    for doc in nlp.pipe(texts, batch_size=64):
        out.append(merge([(e.start_char, e.end_char, None)
                          for e in doc.ents if e.label_ in SPACY_PII_LABELS]))
    return out


def predict_presidio(texts, analyzer):
    out = []
    for t in texts:
        res = analyzer.analyze(text=t, language="en")
        out.append(merge([(r.start, r.end, None) for r in res]))
    return out


def predict_encoder(texts, model, tok, dev, max_len=384):
    """BIO decode using tokenizer offsets. Offsets never come from the model."""
    id2label = model.config.id2label
    out = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i : i + BATCH]
        enc = tok(chunk, truncation=True, max_length=max_len, padding=True,
                  return_offsets_mapping=True, return_tensors="pt")
        offsets = enc.pop("offset_mapping")
        enc = {k: v.to(dev) for k, v in enc.items()}
        with torch.no_grad():
            logits = model(**enc).logits
        preds = logits.argmax(-1).cpu()
        for b in range(len(chunk)):
            spans, cur = [], None
            for j, (s, e) in enumerate(offsets[b].tolist()):
                if s == e:
                    continue
                lab = id2label[int(preds[b][j])]
                if lab == "O":
                    if cur:
                        spans.append(tuple(cur)); cur = None
                    continue
                prefix, cat = lab.split("-", 1)
                if prefix == "B" or cur is None or cur[2] != cat:
                    if cur:
                        spans.append(tuple(cur))
                    cur = [s, e, cat]
                else:
                    cur[1] = e
            if cur:
                spans.append(tuple(cur))
            out.append(spans)
    return out


# --- scoring ---------------------------------------------------------------

def score(truths, preds, want_category: bool):
    tp = fn = 0
    fp = 0
    cat_right = cat_total = 0
    per_cat: dict[str, list[int]] = {}
    for truth, pred in zip(truths, preds):
        used = set()
        for t in truth:
            cat = t[2]
            slot = per_cat.setdefault(cat, [0, 0])
            slot[1] += 1
            hit = None
            for k, p in enumerate(pred):
                if k in used:
                    continue
                if matches(t, p):
                    hit = k
                    break
            if hit is None:
                fn += 1
            else:
                tp += 1
                slot[0] += 1
                used.add(hit)
                if want_category and len(pred[hit]) > 2 and pred[hit][2] is not None:
                    cat_total += 1
                    cat_right += int(pred[hit][2] == cat)
        fp += len(pred) - len(used)
    recall = tp / max(tp + fn, 1)
    precision = tp / max(tp + fp, 1)
    f1 = 2 * recall * precision / max(recall + precision, 1e-9)
    cat_acc = cat_right / cat_total if cat_total else None
    return {"tp": tp, "fp": fp, "fn": fn, "recall": recall, "precision": precision,
            "f1": f1, "cat_acc": cat_acc, "per_cat": per_cat}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="encoder,presidio,spacy,regex")
    ap.add_argument("--skip-transfer", action="store_true")
    ap.add_argument("--model-dir", default=None, help="evaluate a specific checkpoint")
    args = ap.parse_args()
    methods = args.methods.split(",")

    global MODEL_DIR
    if args.model_dir:
        MODEL_DIR = Path(args.model_dir)

    from transformers import AutoModelForTokenClassification, AutoTokenizer

    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    nlp = analyzer = model = tok = None
    if "spacy" in methods:
        import spacy
        nlp = spacy.load("en_core_web_lg")
    if "presidio" in methods:
        from presidio_analyzer import AnalyzerEngine
        analyzer = AnalyzerEngine()
    if "encoder" in methods:
        if not MODEL_DIR.exists():
            print(f"missing {MODEL_DIR} — run scripts/m3_train_encoder.py first")
            return 1
        tok = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForTokenClassification.from_pretrained(
            MODEL_DIR, dtype=torch.float32).to(dev).eval()

    def run(method, texts):
        t0 = time.time()
        if method == "regex":
            p = predict_regex(texts)
        elif method == "spacy":
            p = predict_spacy(texts, nlp)
        elif method == "presidio":
            p = predict_presidio(texts, analyzer)
        else:
            p = predict_encoder(texts, model, tok, dev)
        return p, time.time() - t0

    rows = []
    report: dict[tuple[str, str], dict] = {}

    for dataset in ["stratified", "natural", "seen_templates"]:
        path = SYN / f"injected_{dataset}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        texts = df["text"].tolist()
        truths = [[(s["start"], s["end"], s["category"]) for s in spans] for spans in df["spans"]]
        print(f"\n=== {dataset}: {len(texts):,} narratives, "
              f"{sum(len(t) for t in truths):,} spans ===", flush=True)
        for m in methods:
            preds, secs = run(m, texts)
            r = score(truths, preds, want_category=(m == "encoder"))
            r["seconds"] = secs
            r["per_doc_ms"] = 1000 * secs / max(len(texts), 1)
            report[(dataset, m)] = r
            print(f"  {m:<10} recall {100*r['recall']:5.1f}%  precision {100*r['precision']:5.1f}%"
                  f"  f1 {100*r['f1']:5.1f}%  ({secs:.0f}s)", flush=True)
            rows.append({"dataset": dataset, "method": m, "category": "ALL", "tier": "",
                         "recall_pct": round(100*r["recall"], 2),
                         "precision_pct": round(100*r["precision"], 2),
                         "f1_pct": round(100*r["f1"], 2),
                         "category_accuracy_pct": round(100*r["cat_acc"], 2) if r["cat_acc"] is not None else "",
                         "tp": r["tp"], "fp": r["fp"], "fn": r["fn"],
                         "ms_per_narrative": round(r["per_doc_ms"], 1)})
            for cat, (h, tot) in sorted(r["per_cat"].items()):
                rows.append({"dataset": dataset, "method": m, "category": cat, "tier": TIER.get(cat, ""),
                             "recall_pct": round(100*h/max(tot, 1), 2), "precision_pct": "",
                             "f1_pct": "", "category_accuracy_pct": "", "tp": h, "fp": "",
                             "fn": tot-h, "ms_per_narrative": ""})

    # --- transfer to real marked text -------------------------------------
    if not args.skip_transfer and NARRATIVES.exists():
        df = pd.read_parquet(NARRATIVES, columns=["narrative"])
        marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
        marked = marked.drop_duplicates(subset="narrative")
        texts = marked.sample(n=min(TRANSFER_N, len(marked)), random_state=SEED)["narrative"].tolist()
        truths = [[(m.start(), m.end(), None) for m in MARKER_SPAN.finditer(t)] for t in texts]
        print(f"\n=== transfer (real CFPB marked text): {len(texts):,} narratives, "
              f"{sum(len(t) for t in truths):,} marker spans ===", flush=True)
        for m in methods:
            preds, secs = run(m, texts)
            r = score(truths, preds, want_category=False)
            r["seconds"] = secs
            report[("transfer", m)] = r
            print(f"  {m:<10} recall {100*r['recall']:5.1f}%  ({secs:.0f}s)", flush=True)
            rows.append({"dataset": "transfer", "method": m, "category": "ALL", "tier": "",
                         "recall_pct": round(100*r["recall"], 2), "precision_pct": "",
                         "f1_pct": "", "category_accuracy_pct": "", "tp": r["tp"], "fp": r["fp"],
                         "fn": r["fn"], "ms_per_narrative": round(1000*secs/max(len(texts),1), 1)})

    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m3_comparison.csv", index=False)

    # --- readable report --------------------------------------------------
    L = ["M3 — every method, identical data", "=" * 74, "",
         "Injected spans have realistic surface forms and exact recorded",
         "positions, so unlike M1 this scores recall, precision AND category",
         "accuracy for every method — including regex, which the marker oracle",
         "could not score at all.", ""]

    for dataset in ["stratified", "natural", "seen_templates", "transfer"]:
        present = [m for m in methods if (dataset, m) in report]
        if not present:
            continue
        L += ["-" * 74, dataset.upper(), ""]
        if dataset == "transfer":
            L.append("  Real CFPB text, scored against XXXX markers. No injected templates")
            L.append("  exist here, so nothing can be explained by template memorisation.")
            L.append("  Recall only — the markers cannot support precision (DEFINITIONS.md).")
            L.append("")
            L.append(f"  {'method':<12} {'recall':>8} {'ms/narrative':>14}")
            for m in present:
                r = report[(dataset, m)]
                L.append(f"  {m:<12} {100*r[chr(39)+chr(39)]:>7.1f}%")
        else:
            L.append(f"  {'method':<12} {'recall':>8} {'precision':>10} {'f1':>8} {'cat acc':>9} {'ms/narr':>9}")
            for m in present:
                r = report[(dataset, m)]
                ca = f"{100*r['cat_acc']:.1f}%" if r["cat_acc"] is not None else "n/a"
                L.append(f"  {m:<12} {100*r['recall']:>7.1f}% {100*r['precision']:>9.1f}% "
                         f"{100*r['f1']:>7.1f}% {ca:>9} {r['per_doc_ms']:>9.1f}")
        L.append("")

    # the memorisation diagnostic
    if ("stratified", "encoder") in report and ("seen_templates", "encoder") in report:
        held = report[("stratified", "encoder")]["recall"]
        seen = report[("seen_templates", "encoder")]["recall"]
        L += ["=" * 74, "TEMPLATE MEMORISATION DIAGNOSTIC", "",
              f"  encoder recall, TRAINING templates (seen_templates): {100*seen:.1f}%",
              f"  encoder recall, HELD-OUT templates (stratified):     {100*held:.1f}%",
              f"  gap:                                                 {100*(seen-held):+.1f} pts", "",
              "  A large positive gap means the model learned the carrier phrasing",
              "  rather than what personal information looks like. Near zero means",
              "  the phrasing did not matter, which is what we want. This number is",
              "  reported whatever it says.", ""]

    # per-category, stratified only — that is what it exists for
    if ("stratified", "encoder") in report:
        L += ["-" * 74, "PER-CATEGORY RECALL (stratified set — equal power per category)", "",
              f"  {'category':<18} {'tier':>4} {'n':>7}" + "".join(f"{m:>11}" for m in methods)]
        cats = sorted(report[("stratified", methods[0])]["per_cat"],
                      key=lambda c: (TIER.get(c, 9), c))
        for cat in cats:
            n = report[("stratified", methods[0])]["per_cat"][cat][1]
            cells = ""
            for m in methods:
                pc = report[("stratified", m)]["per_cat"].get(cat, [0, 0])
                cells += f"{100*pc[0]/max(pc[1],1):>10.1f}%"
            L.append(f"  {cat:<18} {TIER.get(cat,''):>4} {n:>7,}{cells}")
        L.append("")
        L.append("  Tier 2 is the contextual identifiers Airlock exists to find.")
        L.append("  Tier 1 includes rows Presidio is expected to win; they are published.")

    out = "\n".join(L)
    (RESULTS / "m3_comparison.txt").write_text(out + "\n")
    print("\n" + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
