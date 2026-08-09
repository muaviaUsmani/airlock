"""
M5: is the redacted text still worth anything?

WHY THIS MILESTONE EXISTS
-------------------------
M4 reports re-identification falling from 36.9% to 0.2%. On its own that number
REWARDS DESTRUCTION — blank every narrative and nothing leaks at all. spaCy
scoring 0.0% there is exactly that failure: it removes five times what it should.

So leakage has to be read against usefulness, and usefulness means: can a
frontier model still answer questions about the complaint after redaction? That
is the whole reason the bank wanted to redact rather than withhold.

WHY THE ANSWERS CAN BE CHECKED WITHOUT A HUMAN
----------------------------------------------
The CFPB publishes structured fields alongside each narrative, filled in by the
CFPB's own intake process rather than by us. Those are the answer key:

    Sub-product   -> "what kind of card is this about?"
    Issue         -> "what is the customer complaining about?"
    Company response -> "did the company give money back?"

So the model is asked questions whose answers already exist as data. No human
grades anything, and no judgement enters the loop — which is what the brief
requires of every headline number.

WHICH MODEL, AND WHY THE CHEAP ONE
----------------------------------
Haiku, deliberately. The measurement is how much the REDACTION costs, not how
clever the reader is. A stronger model would partly compensate for damaged text
by inferring around the gaps, which flatters the redactor and blurs exactly the
difference being measured. A weaker reader makes the comparison sharper.

The same model, temperature and prompt are used for every condition, so the only
thing varying is the text.

Needs ANTHROPIC_API_KEY in the environment. Nothing else in this project needs a
credential; see .secrets/README.md.

Reads:  data/synthetic/injected_natural_v2_hard2.parquet
        data/interim/creditcard_narratives.parquet
        models/<arm>/            (to produce the Airlock-redacted condition)
Writes: results/m5_utility.csv
        results/m5_utility.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SYN = ROOT / "data" / "synthetic"
NARRATIVES = ROOT / "data" / "interim" / "creditcard_narratives.parquet"

MODEL = "claude-haiku-4-5-20251001"
PLACEHOLDER = "[REDACTED]"
SEED = 20260806

QUESTIONS = [
    ("sub_product", "Sub-product",
     "What kind of credit card account is this complaint about?"),
    ("issue", "Issue",
     "What is the customer's main complaint about?"),
    ("relief", "Company response to consumer",
     "Did the company give the customer money back?"),
]


def build_prompt(text: str, options: dict[str, list[str]]) -> str:
    lines = ["Read this consumer complaint, then answer three questions.",
             "Some of it may be redacted as [REDACTED]; answer from what remains.",
             "If the remaining text does not support an answer, reply UNKNOWN for that question.",
             "", "COMPLAINT:", text.strip()[:6000], "", "QUESTIONS:"]
    for i, (key, _, q) in enumerate(QUESTIONS, 1):
        lines.append(f"{i}. {q}")
        lines.append("   Choose exactly one: " + " | ".join(options[key]) + " | UNKNOWN")
    lines += ["", 'Reply as JSON only: {"sub_product": "...", "issue": "...", "relief": "..."}']
    return "\n".join(lines)


def normalise(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).lower().strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--methods", default="raw,presidio,airlock,spacy")
    ap.add_argument("--model-dir", default="models/encoder-base2-s20260806")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. See .secrets/README.md — this is the\n"
              "only part of the project that needs a credential.", file=sys.stderr)
        return 1
    try:
        from anthropic import Anthropic
    except ImportError:
        print("pip install anthropic", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT / "scripts"))
    import m3_evaluate as M3
    import m4_attack as M4

    inj = pd.read_parquet(SYN / "injected_natural_v2_hard2.parquet").head(args.n)
    meta = pd.read_parquet(NARRATIVES,
                           columns=["narrative", "Sub-product", "Issue",
                                    "Company response to consumer"])
    # Recovering the answer key: the injected text embeds a real narrative, but
    # the injector splices carrier sentences in at sentence boundaries INCLUDING
    # the start — so matching on the opening characters fails. The first version
    # of this matched 1 narrative in 6 and silently scored the other five wrong,
    # which showed up as a suspiciously low raw-text score rather than as an
    # error.
    #
    # Original sentences survive verbatim, so match on those instead: index every
    # sufficiently long sentence to its row, then look up the longest sentence in
    # each injected narrative.
    sent_split = re.compile(r"(?<=[.!?])\s+")
    by_sentence = {}
    for _, r in meta.iterrows():
        for sent in sent_split.split(str(r["narrative"])):
            k = normalise(sent)
            if len(k) >= 60:
                by_sentence.setdefault(k, r)

    texts, truth, missed = [], [], 0
    for t in inj["text"]:
        cands = sorted((normalise(x) for x in sent_split.split(t)), key=len, reverse=True)
        hit = next((by_sentence[c] for c in cands[:6] if c in by_sentence), None)
        if hit is None:
            missed += 1
            continue
        texts.append(t)
        truth.append({"sub_product": hit["Sub-product"], "issue": hit["Issue"],
                      "relief": hit["Company response to consumer"]})
    print(f"matched {len(texts):,} of {len(inj):,} narratives to their CFPB fields "
          f"({missed} unmatched, dropped)", flush=True)
    if len(texts) < 0.8 * len(inj):
        print("  WARNING: under 80% matched — grading a biased subset", file=sys.stderr)
    if not texts:
        print("no narratives matched — cannot grade", file=sys.stderr)
        return 1

    options = {
        "sub_product": sorted({str(t["sub_product"]) for t in truth}),
        "issue": sorted({str(t["issue"]) for t in truth})[:12],
        "relief": ["yes", "no"],
    }
    # "Closed with non-monetary relief" CONTAINS "monetary", so a substring test
    # labels non-monetary relief as monetary. Match the exact CFPB category.
    for t in truth:
        t["relief"] = "yes" if normalise(t["relief"]) == "closed with monetary relief" else "no"

    # --- build each redaction condition -----------------------------------
    variants = {"raw": texts}
    methods = [m for m in args.methods.split(",") if m != "raw"]
    for m in methods:
        if m == "spacy":
            import spacy
            nlp = spacy.load("en_core_web_lg")
            preds = M3.predict_spacy(texts, nlp)
        elif m == "presidio":
            from presidio_analyzer import AnalyzerEngine
            preds = M3.predict_presidio(texts, AnalyzerEngine())
        elif m == "airlock":
            import torch
            from transformers import AutoModelForTokenClassification, AutoTokenizer
            dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
            d = ROOT / args.model_dir
            tok = AutoTokenizer.from_pretrained(d)
            mod = AutoModelForTokenClassification.from_pretrained(d, dtype=torch.float32).to(dev).eval()
            preds = M3.predict_encoder(texts, mod, tok, dev)
        else:
            continue
        variants[m] = [M4.redact(t, p) for t, p in zip(texts, preds)]
        print(f"  built {m} condition", flush=True)

    # --- ask ---------------------------------------------------------------
    client = Anthropic()
    rows, per_method = [], {}
    for name, variant in variants.items():
        correct = Counter()
        unknown = Counter()
        asked = 0
        t0 = time.time()
        for i, text in enumerate(variant):
            try:
                r = client.messages.create(
                    model=MODEL, max_tokens=200, temperature=0,
                    messages=[{"role": "user", "content": build_prompt(text, options)}])
                raw = r.content[0].text
                j = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            except Exception:
                continue
            asked += 1
            for key, _, _ in QUESTIONS:
                got = normalise(j.get(key, ""))
                want = normalise(truth[i][key])
                if got == "unknown":
                    unknown[key] += 1
                elif got == want:
                    correct[key] += 1
            if (i + 1) % 50 == 0:
                print(f"    {name}: {i+1}/{len(variant)}", flush=True)
        per_method[name] = {"asked": asked, "correct": correct, "unknown": unknown,
                            "seconds": time.time() - t0}
        overall = sum(correct.values()) / max(asked * len(QUESTIONS), 1)
        print(f"  {name:<10} {100*overall:5.1f}% correct over {asked} narratives "
              f"({time.time()-t0:.0f}s)", flush=True)
        for key, _, _ in QUESTIONS:
            rows.append({"method": name, "question": key, "asked": asked,
                         "correct": correct[key], "unknown": unknown[key],
                         "accuracy_pct": round(100 * correct[key] / max(asked, 1), 2)})

    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m5_utility.csv", index=False)

    L = ["M5 — does the redacted text still answer questions?", "=" * 72, "",
         f"reader: {MODEL} at temperature 0   |   {len(texts):,} complaints", "",
         "Answers are graded against the CFPB's own structured fields, which the",
         "CFPB filled in, not us. No human and no model judges anything.",
         "",
         "The cheap reader is deliberate: this measures what the REDACTION costs,",
         "not how clever the reader is. A stronger model would infer around the",
         "gaps and flatter the redactor.", "",
         f"  {'method':<10} {'overall':>9}" + "".join(f"{k:>16}" for k, _, _ in QUESTIONS)]
    base = None
    for name, r in per_method.items():
        overall = 100 * sum(r["correct"].values()) / max(r["asked"] * len(QUESTIONS), 1)
        if name == "raw":
            base = overall
        cells = "".join(f"{100*r['correct'][k]/max(r['asked'],1):>15.1f}%" for k, _, _ in QUESTIONS)
        L.append(f"  {name:<10} {overall:>8.1f}%{cells}")
    if base is not None:
        L += ["", "-" * 72, "THE TRADE — leakage against usefulness", "",
              f"  {'method':<10} {'re-ident U':>11} {'utility':>9} {'utility lost':>14}"]
        leak = {"raw": 36.9, "presidio": 1.2, "airlock": 0.2, "spacy": 0.0}
        for name, r in per_method.items():
            overall = 100 * sum(r["correct"].values()) / max(r["asked"] * len(QUESTIONS), 1)
            L.append(f"  {name:<10} {leak.get(name, float('nan')):>10.1f}% {overall:>8.1f}% "
                     f"{base-overall:>13.1f}")
        L += ["", "  Re-identification from M4 (natural_v2, 10,000-customer database).",
              "  A redactor is only good if it moves DOWN the first column without",
              "  moving far down the second."]
    text = "\n".join(L)
    (RESULTS / "m5_utility.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
