"""
M1: what do the existing free tools already achieve?

This is the number to beat, and the brief requires it be published before the
thing that beats it is built.

Three baselines, run against the same seeded sample of marked narratives:

  presidio  — Microsoft Presidio, the standard open-source PII detector
  spacy     — spaCy en_core_web_lg named-entity recognition on its own
  regex     — a plain pattern approach, no model at all

Recall is scored against the CFPB XXXX markers, per DEFINITIONS.md: adjacent
markers merge into one span, and a prediction matches when it overlaps a true
span without overrunning it by more than 50%.

READ THIS BEFORE QUOTING THESE NUMBERS
--------------------------------------
The published text does not contain personal information. It contains XXXX where
the personal information used to be. So these detectors are being asked to flag a
token that carries no information — only the surrounding context survives.

A smoke test measured Presidio flagging 45.4% of marker spans, which means it IS
working from context and the measurement is meaningful. But a real name gives a
detector far more to work with than "XXXX" does, so **every number this script
produces understates what the tool would achieve on unredacted text.**

They are therefore a floor, and comparable to each other on this substrate. They
are NOT "what Presidio achieves in production", and nothing in this repository
may quote them that way. The like-for-like comparison happens on injected data
(M2), where every method sees realistic surface forms.

Category breakdown is by ESTIMATED category, inferred from the words surviving
around each marker, per DEFINITIONS.md section 2. The CFPB oracle cannot support
true category labels because the original text is gone.

Reads:  data/interim/creditcard_narratives.parquet
Writes: results/m1_baselines.csv
        results/m1_baselines.txt
"""

import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
OUT_CSV = ROOT / "results" / "m1_baselines.csv"
OUT_TXT = ROOT / "results" / "m1_baselines.txt"

SEED = 20260806
SAMPLE = 15_000

# Per DEFINITIONS.md: adjacent markers, and markers joined by slashes, are ONE
# span. Without this a redacted street address counts as four detections.
MARKER_SPAN = re.compile(
    r"(?<![A-Za-z0-9])X{2,}(?:\s*/\s*(?:X{2,4}|\d{2,4})|[ \t]+X{2,})*(?![A-Za-z0-9])"
)

# Overrun tolerance from DEFINITIONS.md: a prediction may not extend more than
# 50% of the true span's length beyond it.
OVERRUN = 0.5

# --- estimated category rules ---------------------------------------------
# Inferred from surviving left context. These are ESTIMATES and are labelled as
# such everywhere they appear. Built from the M0 context mining, not invented.
CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("DATE", re.compile(r"$^")),  # filled by shape, handled separately
    ("ACCOUNT_ID", re.compile(r"(ending|ends)\s+(in\s+)?$|account\s+(#\s*)?$|card\s+(#\s*)?$", re.I)),
    ("CASE_REF", re.compile(r"(case|claim|complaint|reference|ref|confirmation)\s*#?\s*$", re.I)),
    ("CONTACT", re.compile(r"(phone|call(ed)?\s+at|number\s+of|fax|email)\s*$", re.I)),
    ("PERSON", re.compile(r"(named|name\s+is|sincerely|regards|mr|mrs|ms|dr)\.?\s*$", re.I)),
    ("ORG_OR_PERSON", re.compile(r"(called|contacted|spoke\s+(with|to)|with|from|at)\s+$", re.I)),
    ("LOCATION", re.compile(r"(in|at|to|from)\s+(the\s+)?(city|state|branch|store)\s+(of\s+)?$", re.I)),
    ("AMOUNT_OR_COUNT", re.compile(r"(\$|of\s+\$?)\s*$", re.I)),
]

DATE_SHAPE = re.compile(r"^X{2}\s*/\s*X{2}\s*/\s*(?:X{2,4}|\d{2,4})$|^X{2}\s*/\s*(?:X{2,4}|\d{2,4})$")
NON_PII_TRAILING = re.compile(r"^\s*(points?|days?|months?|years?|weeks?|hours?|times?|bureaus?|%|percent)\b", re.I)


def estimate_category(text: str, start: int, end: int) -> str:
    """Best guess at what a marker replaced, from surviving context. An estimate."""
    span = text[start:end]
    if DATE_SHAPE.match(span.strip()):
        return "DATE"
    # A marker followed by a unit word is a count or rate, not personal info.
    if NON_PII_TRAILING.match(text[end : end + 20]):
        return "NOT_PII_ESTIMATED"
    left = text[max(0, start - 40) : start]
    for name, pattern in CATEGORY_RULES:
        if name == "DATE":
            continue
        if pattern.search(left):
            return name
    return "UNKNOWN"


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Collapse overlapping predictions so one name predicted twice counts once."""
    if not spans:
        return []
    spans = sorted(spans)
    out = [spans[0]]
    for s, e in spans[1:]:
        if s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def matches(true: tuple[int, int], pred: tuple[int, int]) -> bool:
    """DEFINITIONS.md match rule: overlap, without overrunning by >50%."""
    ts, te = true
    ps, pe = pred
    if not (ps < te and ts < pe):
        return False
    true_len = max(te - ts, 1)
    overrun = max(0, ts - ps) + max(0, pe - te)
    return overrun <= OVERRUN * true_len


# --- the three baselines ---------------------------------------------------

REGEX_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                        # SSN
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),                      # card number
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),                  # email
    re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),  # phone
    re.compile(r"\bhttps?://\S+\b"),                             # url
    re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane)\b"),
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),                         # zip
]

SPACY_PII_LABELS = {"PERSON", "GPE", "LOC", "ORG", "FAC", "DATE", "NORP"}


def run_regex(texts: list[str]) -> list[list[tuple[int, int]]]:
    return [
        merge_spans([(m.start(), m.end()) for p in REGEX_PATTERNS for m in p.finditer(t)])
        for t in texts
    ]


def run_spacy(texts: list[str], nlp) -> list[list[tuple[int, int]]]:
    out = []
    for doc in nlp.pipe(texts, batch_size=64):
        out.append(
            merge_spans(
                [(e.start_char, e.end_char) for e in doc.ents if e.label_ in SPACY_PII_LABELS]
            )
        )
    return out


def run_presidio(texts: list[str], analyzer) -> list[list[tuple[int, int]]]:
    out = []
    for i, t in enumerate(texts):
        res = analyzer.analyze(text=t, language="en")
        out.append(merge_spans([(r.start, r.end) for r in res]))
        if i and i % 2000 == 0:
            print(f"    presidio {i:,}/{len(texts):,}", flush=True)
    return out


def score(
    texts: list[str],
    truths: list[list[tuple[int, int]]],
    cats: list[list[str]],
    preds: list[list[tuple[int, int]]],
) -> tuple[int, int, dict[str, list[int]]]:
    hit = 0
    total = 0
    by_cat: dict[str, list[int]] = {}
    for truth, cat, pred in zip(truths, cats, preds):
        for (t, c) in zip(truth, cat):
            total += 1
            found = any(matches(t, p) for p in pred)
            hit += found
            slot = by_cat.setdefault(c, [0, 0])
            slot[0] += found
            slot[1] += 1
    return hit, total, by_cat


def main() -> int:
    if not IN.exists():
        print(f"missing {IN} — run scripts/m0_extract.py first", file=sys.stderr)
        return 1

    import spacy
    from presidio_analyzer import AnalyzerEngine

    df = pd.read_parquet(IN, columns=["complaint_id", "narrative"])
    marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
    sample = marked.sample(n=min(SAMPLE, len(marked)), random_state=SEED)
    texts = sample["narrative"].tolist()

    truths, cats = [], []
    for t in texts:
        spans = [(m.start(), m.end()) for m in MARKER_SPAN.finditer(t)]
        truths.append(spans)
        cats.append([estimate_category(t, s, e) for s, e in spans])

    n_spans = sum(len(s) for s in truths)
    print(f"scoring {len(texts):,} narratives, {n_spans:,} merged marker spans\n")

    print("loading models...", flush=True)
    nlp = spacy.load("en_core_web_lg")
    analyzer = AnalyzerEngine()

    runs = {}
    for name, fn in [
        ("regex", lambda: run_regex(texts)),
        ("spacy", lambda: run_spacy(texts, nlp)),
        ("presidio", lambda: run_presidio(texts, analyzer)),
    ]:
        print(f"  running {name}...", flush=True)
        t0 = time.time()
        preds = fn()
        elapsed = time.time() - t0
        hit, total, by_cat = score(texts, truths, cats, preds)
        runs[name] = {
            "hit": hit,
            "total": total,
            "by_cat": by_cat,
            "seconds": elapsed,
            "predictions": sum(len(p) for p in preds),
        }
        print(f"    {name}: {hit:,}/{total:,} = {100*hit/max(total,1):.1f}%  ({elapsed:.0f}s)")

    # --- write results ----------------------------------------------------
    rows = []
    for name, r in runs.items():
        rows.append(
            {
                "method": name,
                "category": "ALL",
                "markers_found": r["hit"],
                "markers_total": r["total"],
                "recall_pct": round(100 * r["hit"] / max(r["total"], 1), 2),
                "predictions_made": r["predictions"],
                "seconds": round(r["seconds"], 1),
            }
        )
        for cat, (h, t) in sorted(r["by_cat"].items(), key=lambda kv: -kv[1][1]):
            rows.append(
                {
                    "method": name,
                    "category": cat,
                    "markers_found": h,
                    "markers_total": t,
                    "recall_pct": round(100 * h / max(t, 1), 2),
                    "predictions_made": "",
                    "seconds": "",
                }
            )
    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    L = [
        "M1 — baseline recall against CFPB XXXX markers",
        "=" * 62,
        "",
        f"sample:        {len(texts):,} narratives (seed {SEED})",
        f"marker spans:  {n_spans:,} after adjacent-merge, per DEFINITIONS.md",
        "",
        "!! THESE NUMBERS ARE A FLOOR, NOT A PRODUCTION BENCHMARK !!",
        "The text contains XXXX where the personal information used to be, so",
        "every detector is working from context alone with no surface form to",
        "read. All three are understated by an unmeasured amount, equally.",
        "The like-for-like comparison happens on injected data at M2.",
        "",
        "-" * 62,
        "OVERALL RECALL",
        "",
        f"  {'method':<12} {'recall':>8}   {'found':>9} / {'total':<9}  {'preds':>8}  {'sec':>6}",
    ]
    for name, r in sorted(runs.items(), key=lambda kv: -kv[1]["hit"]):
        L.append(
            f"  {name:<12} {100*r['hit']/max(r['total'],1):>7.1f}%   "
            f"{r['hit']:>9,} / {r['total']:<9,}  {r['predictions']:>8,}  {r['seconds']:>6.0f}"
        )
    L += ["", "-" * 62, "RECALL BY ESTIMATED CATEGORY", "",
          "Categories are INFERRED from surviving context, not known. The CFPB",
          "oracle cannot supply true categories — the original text is gone.",
          "NOT_PII_ESTIMATED marks spans that context says were counts or rates,",
          "where a low score is CORRECT behaviour, not a miss.",
          ""]
    all_cats = sorted(
        {c for r in runs.values() for c in r["by_cat"]},
        key=lambda c: -max(r["by_cat"].get(c, [0, 0])[1] for r in runs.values()),
    )
    L.append(f"  {'category':<22} {'n':>7}  " + "  ".join(f"{m:>9}" for m in runs))
    for c in all_cats:
        n = max(r["by_cat"].get(c, [0, 0])[1] for r in runs.values())
        cells = []
        for m in runs:
            h, t = runs[m]["by_cat"].get(c, [0, 0])
            cells.append(f"{100*h/max(t,1):>8.1f}%")
        L.append(f"  {c:<22} {n:>7,}  " + "  ".join(cells))

    text_out = "\n".join(L)
    OUT_TXT.write_text(text_out + "\n")
    print("\n" + text_out)
    print(f"\nwrote {OUT_CSV}\nwrote {OUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
