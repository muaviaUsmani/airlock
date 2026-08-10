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
    ap.add_argument("--model-dir", default="models/encoder-base2-s20260806",
                    help="deprecated; use --airlock-dirs")
    ap.add_argument("--airlock-dirs",
                    default="models/encoder-micro-s20260806,models/encoder-base2-s20260806",
                    help="comma-separated encoder dirs, one airlock condition each")
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

    # 8.4% of the corpus (11.2% of the graded slice) has no CFPB Sub-product.
    # str(nan) is the string "nan", which previously did two bad things at once:
    # it became the answer key for those rows, which no reader can produce, AND
    # sorted({...}) put "nan" into the option list, so it was offered to the
    # reader as a valid choice on EVERY row. A row with no answer key is not a
    # question the reader got wrong; it is not a question at all, so it is
    # excluded from that question's denominator rather than scored as a miss.
    for t in truth:
        for key, _, _ in QUESTIONS:
            if pd.isna(t[key]) or normalise(t[key]) in ("", "nan", "none"):
                t[key] = None

    # Every label that actually appears in the graded slice is offered. The
    # previous version capped `issue` at sorted(...)[:12] -- the first twelve
    # ALPHABETICALLY out of 27 present -- so only 32.6% of the true answers were
    # even reachable, and the two most common ones were missing because they
    # start with "P" and "O". That capped the question at 32.6% before the
    # reader saw a word of text, and it read as poor comprehension rather than
    # as a broken option list. There is no cap now: a longer list makes the
    # question harder, which is fine, but an unreachable answer makes it wrong.
    options = {
        "sub_product": sorted({str(t["sub_product"]) for t in truth if t["sub_product"]}),
        "issue": sorted({str(t["issue"]) for t in truth if t["issue"]}),
        "relief": ["yes", "no"],
    }
    # "Closed with non-monetary relief" CONTAINS "monetary", so a substring test
    # labels non-monetary relief as monetary. Match the exact CFPB category.
    for t in truth:
        if t["relief"] is not None:
            t["relief"] = "yes" if normalise(t["relief"]) == "closed with monetary relief" else "no"

    # Majority-class baseline: what a reader scores by ignoring the text entirely
    # and always naming the most common label. A question whose accuracy sits
    # below its baseline is measuring the base rate, not the narrative, and that
    # is worth seeing next to the number rather than discovering later.
    baseline, gradable = {}, {}
    for key, _, _ in QUESTIONS:
        vals = [normalise(t[key]) for t in truth if t[key] is not None]
        gradable[key] = len(vals)
        baseline[key] = Counter(vals).most_common(1)[0][1] / len(vals) if vals else 0.0
    # Invariant: a correct answer must always be available to the reader. This
    # is checked rather than assumed, because both ways it has been violated in
    # this script produced a plausible low score instead of an error -- once via
    # a "nan" answer key, once via an alphabetically truncated option list.
    print("  gradable rows / majority baseline per question:", flush=True)
    unreachable = False
    for key, _, _ in QUESTIONS:
        opts = {normalise(o) for o in options[key]}
        vals = [t[key] for t in truth if t[key] is not None]
        miss = sum(1 for v in vals if normalise(v) not in opts)
        note = f"{len(options[key])} options"
        if miss:
            unreachable = True
            note = (f"UNREACHABLE {miss}/{len(vals)} true answers missing from options "
                    f"-> question capped at {100*(len(vals)-miss)/len(vals):.1f}%")
        print(f"    {key:<12} {gradable[key]:>4} rows   baseline {100*baseline[key]:5.1f}%   {note}",
              flush=True)
    if unreachable:
        print("  !! at least one question cannot be answered correctly for some rows;\n"
              "     the scores below understate every method equally.", file=sys.stderr)

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
            # cuda first: a previous eval script checked only mps and silently
            # ran on CPU with the GPU at 0% utilisation.
            dev = torch.device("cuda" if torch.cuda.is_available()
                               else "mps" if torch.backends.mps.is_available() else "cpu")
            # One condition per arm. Which encoder supplies the airlock condition
            # changes the published utility number, so both are run and compared
            # rather than one being picked.
            for d_rel in [x for x in args.airlock_dirs.split(",") if x]:
                d = ROOT / d_rel
                if not (d / "model.safetensors").exists():
                    print(f"  SKIP airlock arm {d_rel}: no weights at {d}", file=sys.stderr)
                    continue
                tok = AutoTokenizer.from_pretrained(d)
                mod = AutoModelForTokenClassification.from_pretrained(
                    d, dtype=torch.float32).to(dev).eval()
                p = M3.predict_encoder(texts, mod, tok, dev)
                arm = d.name.replace("encoder-", "").split("-s")[0]
                variants[f"airlock:{arm}"] = [M4.redact(t, x) for t, x in zip(texts, p)]
                print(f"  built airlock:{arm} condition from {d_rel}", flush=True)
                del mod
            continue
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
        graded = Counter()
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
                # No answer key for this row and question -> not a question.
                if truth[i][key] is None:
                    continue
                graded[key] += 1
                got = normalise(j.get(key, ""))
                want = normalise(truth[i][key])
                if got == "unknown":
                    unknown[key] += 1
                elif got == want:
                    correct[key] += 1
            if (i + 1) % 50 == 0:
                print(f"    {name}: {i+1}/{len(variant)}", flush=True)
        per_method[name] = {"asked": asked, "correct": correct, "unknown": unknown,
                            "graded": graded, "seconds": time.time() - t0}
        overall = sum(correct.values()) / max(sum(graded.values()), 1)
        print(f"  {name:<10} {100*overall:5.1f}% correct over {asked} narratives "
              f"({time.time()-t0:.0f}s)", flush=True)
        for key, _, _ in QUESTIONS:
            acc = 100 * correct[key] / max(graded[key], 1)
            rows.append({"method": name, "question": key, "asked": asked,
                         "graded": graded[key], "correct": correct[key],
                         "unknown": unknown[key],
                         "accuracy_pct": round(acc, 2),
                         "baseline_pct": round(100 * baseline[key], 2),
                         "over_baseline_pct": round(acc - 100 * baseline[key], 2)})

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
         f"  {'method':<16} {'overall':>9}" + "".join(f"{k:>16}" for k, _, _ in QUESTIONS)]
    base = None
    for name, r in per_method.items():
        overall = 100 * sum(r["correct"].values()) / max(sum(r["graded"].values()), 1)
        if name == "raw":
            base = overall
        cells = "".join(f"{100*r['correct'][k]/max(r['graded'][k],1):>15.1f}%"
                        for k, _, _ in QUESTIONS)
        L.append(f"  {name:<16} {overall:>8.1f}%{cells}")

    # The baseline row is the point of the table: a question sitting below it is
    # reporting the base rate rather than anything the reader read.
    L += ["  " + "-" * 74,
          f"  {'majority baseline':<16} {'':>9}"
          + "".join(f"{100*baseline[k]:>15.1f}%" for k, _, _ in QUESTIONS),
          f"  {'gradable rows':<16} {'':>9}"
          + "".join(f"{gradable[k]:>16}" for k, _, _ in QUESTIONS),
          "",
          f"  Only `issue` ({len(options['issue'])} labels here) has enough spread for",
          "  accuracy to mean much; sub_product and relief are both 2-way, so their",
          "  baselines sit near 90% and neither reader beats one. Rows where the CFPB",
          "  left the field empty are excluded from that question's denominator rather",
          "  than scored as misses, and every label present is offered as an option --",
          "  an earlier version capped the list alphabetically and made two thirds of",
          "  the correct answers unreachable."]
    if base is not None:
        L += ["", "-" * 72, "THE TRADE — leakage against usefulness", "",
              f"  {'method':<16} {'re-ident U':>11} {'utility':>9} {'utility lost':>14}"]
        # These come from an M4 run against a 10,000-customer database. They were
        # a bare hardcoded dict with no provenance, which is how they drifted out
        # of agreement with results/m4_attack.txt without anything noticing: the
        # canonical database is currently 40,000 customers, where raw scores
        # 14.3% rather than 36.9%. Re-identification is strongly population
        # dependent (results/m6_dbsize.txt), so a leakage number means nothing
        # without the database size attached.
        #
        # Preference order: read the live M4 run; fall back to the recorded 10k
        # sweep; say which was used either way.
        LEAK_10K = {"raw": 36.9, "presidio": 1.2, "airlock": 0.2, "spacy": 0.0}
        leak, leak_src = dict(LEAK_10K), "recorded 10,000-customer sweep (m6_dbsize)"
        m4_csv = RESULTS / "m4_attack.csv"
        if m4_csv.exists():
            try:
                m4 = pd.read_csv(m4_csv)
                best = m4[m4.method == "raw"].sort_values("U_unique_pct", ascending=False).iloc[0]
                sub = m4[(m4.fields == best.fields) & (m4.amount_tol == best.amount_tol) &
                         (m4.date_tol_days == best.date_tol_days)]
                live = {str(r["method"]): float(r["U_unique_pct"]) for _, r in sub.iterrows()}
                if "raw" in live:
                    leak.update(live)
                    leak_src = f"live results/m4_attack.csv (raw U = {live['raw']:.1f}%)"
            except Exception as e:  # never let a reporting nicety kill the run
                print(f"  (could not read m4_attack.csv: {e})", file=sys.stderr)
        for name, r in per_method.items():
            overall = 100 * sum(r["correct"].values()) / max(sum(r["graded"].values()), 1)
            # "airlock:micro" and "airlock:base2" share M4's airlock leakage
            # figure, which was measured for the arm named in M4, not per-arm.
            u = leak.get(name.split(":")[0], float("nan"))
            L.append(f"  {name:<16} {u:>10.1f}% {overall:>8.1f}% "
                     f"{base-overall:>13.1f}")
        L += ["", f"  Re-identification source: {leak_src}.",
              "  That number is POPULATION DEPENDENT — raw text scores 19.1% against",
              "  2,500 customers, 36.9% against 10,000 and 14.3% against 40,000",
              "  (results/m6_dbsize.txt). A leakage rate quoted without its database",
              "  size is not a number. The utility column beside it does not move.",
              "",
              "  A redactor is only good if it moves DOWN the first column without",
              "  moving far down the second."]
    text = "\n".join(L)
    (RESULTS / "m5_utility.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
