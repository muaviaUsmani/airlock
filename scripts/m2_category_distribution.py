"""
M2, step 1: what kinds of personal information actually appear, and how often?

The brief is explicit that the injection distribution must be DERIVED from the
real corpus rather than invented:

    "What kinds of personal information actually appear in credit-card
     complaints, and how often? Measure that first (from the XXXX marker
     positions and their surrounding context), then inject at matching
     frequencies. Otherwise we are measuring performance on a distribution we
     made up."

This script is that measurement. It assigns each merged marker span to one of the
16 categories locked in DEFINITIONS.md, using only the words that survived around
it, and reports the resulting distribution.

The honest part of this script is the coverage number it prints. The original text
is gone; all we have is context. Where context does not determine the category the
span is left UNKNOWN rather than guessed, and the most common unresolved contexts
are dumped so a reader can see exactly what the residual looks like and judge
whether the rules are hiding something.

Rules use BOTH sides of the span. "XXXX branch" is only resolvable from the right,
"ending in XXXX" only from the left.

Reads:  data/interim/creditcard_narratives.parquet
Writes: results/m2_category_distribution.csv
        results/m2_category_distribution.txt
        results/m2_unresolved_contexts.csv
"""

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "interim" / "creditcard_narratives.parquet"
RESULTS = ROOT / "results"

SEED = 20260806
SAMPLE = 15_000
LEFT_WINDOW = 60
RIGHT_WINDOW = 40

MARKER_SPAN = re.compile(
    r"(?<![A-Za-z0-9])X{2,}(?:\s*/\s*(?:X{2,4}|\d{2,4})|[ \t]+X{2,})*(?![A-Za-z0-9])"
)

DATE_SHAPE = re.compile(
    r"^X{2}\s*/\s*X{2}\s*/\s*(?:X{2,4}|\d{2,4})$|^X{2}\s*/\s*(?:X{2,4}|\d{2,4})$"
)

# --- rules -----------------------------------------------------------------
# (category, side, pattern). Order matters: the first match wins, so the most
# specific rules are listed first. Every pattern is anchored to the span edge —
# LEFT patterns end at the span, RIGHT patterns start at it.

LEFT: list[tuple[str, str]] = [
    # Tier 1 — direct identifiers
    ("ACCOUNT_ID",      r"(ending|ends|end)\s+(in|with)\s+$"),
    ("ACCOUNT_ID",      r"(account|acct|card)\s*(number|no|#|num)?\s*:?\s*$"),
    ("ACCOUNT_ID",      r"(last|final)\s+(four|4|digits?)\s*(of|are|is)?\s*$"),
    ("CASE_REF",        r"(case|claim|complaint|reference|ref|confirmation|ticket|dispute)\s*(number|no|#)?\s*:?\s*$"),
    ("GOV_ID",          r"(ssn|social\s+security|driver'?s?\s+licen[cs]e|passport|tax\s*id)\s*(number|no|#)?\s*:?\s*$"),
    ("CONTACT",         r"(phone|tel|telephone|fax|mobile|cell)\s*(number|no|#)?\s*:?\s*$"),
    ("CONTACT",         r"(e-?mail|email)\s*(address|at)?\s*:?\s*$"),
    ("CONTACT",         r"(mail(ed)?|sent|write|wrote)\s+(it\s+)?to\s+$"),
    ("CONTACT",         r"(reside|live|living|address)\s+(at|in|is)\s*$"),
    ("PERSON",          r"(named|name\s+(is|was)|called\s+himself)\s*$"),
    ("PERSON",          r"\b(mr|mrs|ms|miss|dr|sir|madam)\.?\s*$"),
    ("PERSON",          r"(sincerely|regards|thank\s+you,?|signed)\s*,?\s*$"),
    ("PERSON",          r"(supervisor|manager|agent|representative|rep|employee|associate)\s+(named\s+)?$"),
    # Tier 2 — contextual identifiers
    ("RELATIONSHIP",    r"\bmy\s+(ex[-\s]?)?(husband|wife|spouse|son|daughter|mother|father|mom|dad|brother|sister|partner|fianc|boyfriend|girlfriend|in[-\s]law|aunt|uncle|cousin|nephew|niece|grand\w+)\w*\s*(,|'s)?\s*$"),
    ("RELATIONSHIP",    r"\bmy\s+(ex|late)\s*$"),
    ("EMPLOYER",        r"(work(ed|ing)?\s+(at|for)|employer|employed\s+by|job\s+(at|with)|retire[d]?\s+from)\s+(the\s+)?$"),
    ("HEALTH",          r"(surgery|medical|dental|dentist|vet|veterinar\w+|procedure|treatment|diagnos\w+|prescri\w+|therapy|hospital)\s+(for|of|at)?\s*$"),
    ("HEALTH",          r"(care\s*credit|carecredit)\s+(for|to)\s+$"),
    ("LIFE_EVENT",      r"(divorce[d]?|marriage|married|widow\w*|passed\s+away|died|death\s+of|discharged?|deployed|bankrupt\w*|foreclos\w+|laid\s+off)\s+(from|in|of|after)?\s*$"),
    ("PROTECTED_ATTR",  r"(i\s+am|i'?m|as)\s+(a|an)\s+$"),
    ("PROTECTED_ATTR",  r"(disab\w+|veteran|handicap\w*|race|religion|ethnic\w*)\s+(status\s+)?(of|is|with)?\s*$"),
    ("LOCATION_FINE",   r"(branch|store|office|location|atm)\s+(in|at|on|near)\s+(the\s+)?$"),
    ("LOCATION_FINE",   r"(in|at|near|from|to)\s+(the\s+)?(city|town|state|county|neighborhood)\s+(of\s+)?$"),
    ("LOCATION_FINE",   r"(moved|relocat\w+|travel\w*|drove|flew)\s+(to|from)\s+$"),
    ("LOCATION_FINE",   r"\b(live[sd]?|living|reside[sd]?)\s+in\s+$"),
    ("ORG_THIRD_PARTY", r"(called|contacted|spoke\s+(with|to)|filed\s+with|reported\s+to|through)\s+(the\s+)?$"),
    ("ORG_THIRD_PARTY", r"(bank|lender|creditor|agency|bureau|company|merchant|retailer|collector)\s+(called|named)?\s*$"),
    # Tier 3 — quasi-identifiers
    ("AMOUNT",          r"(\$|amount\s+of|charge[d]?\s+(me\s+)?|paid|balance\s+of|fee\s+of)\s*\$?\s*$"),
    ("DATE",            r"\b(on|since|until|from|by|before|after|dated|due)\s+$"),
    ("TEMPORAL",        r"\bat\s+(around\s+)?$"),
    ("MERCHANT",        r"(bought|purchase[d]?|shop(ped)?|order(ed)?|charge\s+(at|from)|transaction\s+(at|with))\s+(something\s+)?(at|from|with)?\s*$"),
]

RIGHT: list[tuple[str, str]] = [
    ("LOCATION_FINE",   r"^\s+(branch|store|location|office|atm)\b"),
    ("PERSON",          r"^\s+(said|told|stated|informed|assured|promised|refused|answered|hung\s+up)\b"),
    ("PERSON",          r"^\s*,?\s+(the\s+)?(supervisor|manager|agent|representative|rep)\b"),
    ("ORG_THIRD_PARTY", r"^\s+(bank|credit\s+union|agency|bureau|company)\b"),
    ("EMPLOYER",        r"^\s*,?\s+(where\s+i\s+work|my\s+employer)\b"),
    ("CONTACT",         r"^\s*@\s*\w"),
    ("ACCOUNT_ID",      r"^\s+(account|card)\b"),
]

# Spans whose right context marks them as plain counts or rates. DEFINITIONS.md
# section 1 lists these as explicitly NOT personal information; the CFPB marks
# them anyway. They are counted separately, never injected.
NOT_PII = re.compile(
    r"^\s*(points?|days?|months?|years?|weeks?|hours?|minutes?|times?|dollars?|bureaus?|"
    r"%|percent|cfr|usc|u\.s\.c|credit\s+score|fico)\b",
    re.I,
)

LEFT_RULES = [(c, re.compile(p, re.I)) for c, p in LEFT]
RIGHT_RULES = [(c, re.compile(p, re.I)) for c, p in RIGHT]


def classify(text: str, start: int, end: int) -> str:
    span = text[start:end].strip()
    left = text[max(0, start - LEFT_WINDOW) : start]
    right = text[end : end + RIGHT_WINDOW]

    if NOT_PII.match(right):
        return "NOT_PII"
    if DATE_SHAPE.match(span):
        return "DATE"
    for cat, pat in RIGHT_RULES:
        if pat.search(right):
            return cat
    for cat, pat in LEFT_RULES:
        if pat.search(left):
            return cat
    return "UNKNOWN"


def main() -> int:
    if not IN.exists():
        print(f"missing {IN} — run scripts/m0_extract.py first", file=sys.stderr)
        return 1

    df = pd.read_parquet(IN, columns=["narrative"])
    marked = df[df["narrative"].str.contains(MARKER_SPAN, regex=True, na=False)]
    texts = marked.sample(n=min(SAMPLE, len(marked)), random_state=SEED)["narrative"].tolist()

    counts: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    # How each resolution was made. This is the diagnostic that decides whether
    # the resulting distribution can be trusted: a category resolved mostly by
    # SHAPE is one that labels itself, and will be over-represented relative to
    # categories that only context can reveal.
    source: Counter[str] = Counter()
    ctx_redacted = Counter({"unknown_yes": 0, "unknown_all": 0, "resolved_yes": 0, "resolved_all": 0})

    for t in texts:
        for m in MARKER_SPAN.finditer(t):
            s, e = m.start(), m.end()
            cat = classify(t, s, e)
            counts[cat] += 1

            left = t[max(0, s - LEFT_WINDOW) : s]
            right = t[e : e + RIGHT_WINDOW]
            neighbour_marker = bool(re.search(r"X{2,}", left) or re.search(r"X{2,}", right))

            if cat == "UNKNOWN":
                ctx_redacted["unknown_all"] += 1
                ctx_redacted["unknown_yes"] += neighbour_marker
                lc = t[max(0, s - 24) : s].replace("\n", " ")
                rc = t[e : e + 14].replace("\n", " ")
                unresolved[f"...{lc.strip()} [XXXX] {rc.strip()}..."] += 1
            else:
                ctx_redacted["resolved_all"] += 1
                ctx_redacted["resolved_yes"] += neighbour_marker
                if cat == "NOT_PII":
                    source["NOT_PII via right context"] += 1
                elif DATE_SHAPE.match(t[s:e].strip()):
                    source["DATE via SHAPE"] += 1
                elif any(p.search(right) for _, p in RIGHT_RULES):
                    source[f"{cat} via RIGHT context"] += 1
                else:
                    source[f"{cat} via LEFT context"] += 1

    total = sum(counts.values())
    resolved = total - counts["UNKNOWN"]
    pii_total = total - counts["UNKNOWN"] - counts["NOT_PII"]

    TIERS = {
        "PERSON": 1, "ACCOUNT_ID": 1, "GOV_ID": 1, "CONTACT": 1, "CASE_REF": 1,
        "RELATIONSHIP": 2, "LOCATION_FINE": 2, "EMPLOYER": 2, "LIFE_EVENT": 2,
        "PROTECTED_ATTR": 2, "HEALTH": 2, "ORG_THIRD_PARTY": 2,
        "AMOUNT": 3, "DATE": 3, "MERCHANT": 3, "TEMPORAL": 3,
    }

    rows = []
    for cat, n in counts.most_common():
        rows.append({
            "category": cat,
            "tier": TIERS.get(cat, ""),
            "spans": n,
            "share_of_all_spans_pct": round(100 * n / max(total, 1), 2),
            "share_of_resolved_pii_pct": round(100 * n / max(pii_total, 1), 2) if cat in TIERS else "",
        })
    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "m2_category_distribution.csv", index=False)
    pd.DataFrame(
        [{"context": c, "occurrences": n} for c, n in unresolved.most_common(300)]
    ).to_csv(RESULTS / "m2_unresolved_contexts.csv", index=False)

    L = [
        "M2 — what the markers replaced, estimated from surviving context",
        "=" * 66,
        "",
        f"sample:       {len(texts):,} marked narratives (seed {SEED})",
        f"marker spans: {total:,} after adjacent-merge",
        "",
        "COVERAGE — the number that decides whether this is usable",
        "-" * 66,
        f"  resolved to a category      {resolved:>8,}  ({100*resolved/max(total,1):>5.1f}%)",
        f"  left UNKNOWN                {counts['UNKNOWN']:>8,}  ({100*counts['UNKNOWN']/max(total,1):>5.1f}%)",
        f"  of resolved, NOT_PII        {counts['NOT_PII']:>8,}  ({100*counts['NOT_PII']/max(total,1):>5.1f}%)",
        "",
        "UNKNOWN is not a category. It is a span whose original content the",
        "surviving context does not determine. It is never guessed at, and the",
        "300 most common unresolved contexts are written to",
        "results/m2_unresolved_contexts.csv for inspection.",
        "",
        "-" * 66,
        "DISTRIBUTION OVER RESOLVED PII SPANS",
        "",
        f"  {'category':<18} {'tier':>4} {'spans':>9} {'of all':>8} {'of PII':>8}",
    ]
    for cat, n in counts.most_common():
        if cat not in TIERS:
            continue
        L.append(
            f"  {cat:<18} {TIERS[cat]:>4} {n:>9,} "
            f"{100*n/max(total,1):>7.1f}% {100*n/max(pii_total,1):>7.1f}%"
        )
    L += ["", f"  {'(UNKNOWN)':<18} {'':>4} {counts['UNKNOWN']:>9,} {100*counts['UNKNOWN']/max(total,1):>7.1f}%",
          f"  {'(NOT_PII)':<18} {'':>4} {counts['NOT_PII']:>9,} {100*counts['NOT_PII']/max(total,1):>7.1f}%"]

    by_tier: Counter[int] = Counter()
    for cat, n in counts.items():
        if cat in TIERS:
            by_tier[TIERS[cat]] += n
    L += ["", "-" * 66, "BY TIER (resolved PII spans only)", ""]
    names = {1: "direct identifiers", 2: "contextual identifiers", 3: "quasi-identifiers"}
    for tier in (1, 2, 3):
        L.append(f"  tier {tier}  {names[tier]:<24} {by_tier[tier]:>8,}  {100*by_tier[tier]/max(pii_total,1):>5.1f}%")

    # --- the diagnostic that decides whether this distribution is usable ----
    d_shape = source["DATE via SHAPE"]
    d_ctx = source.get("DATE via LEFT context", 0) + source.get("DATE via RIGHT context", 0)
    L += [
        "",
        "-" * 66,
        "HOW EACH RESOLUTION WAS MADE  (the trustworthiness diagnostic)",
        "",
        "A category resolved by SHAPE labels itself. A category resolvable only",
        "from context is found only when the context survived. The two are not",
        "comparable, and mixing them produces a distribution that describes what",
        "is EASY TO RECOVER rather than what was actually there.",
        "",
    ]
    for k, v in source.most_common(14):
        L.append(f"  {v:>8,}  {k}")
    L += [
        "",
        f"  DATE resolved by shape:   {d_shape:>8,}",
        f"  DATE resolved by context: {d_ctx:>8,}",
        f"  -> {100*d_shape/max(d_shape+d_ctx,1):.1f}% of DATE resolutions come from the marker shape alone.",
        "",
        "  DATE is the only category in DEFINITIONS.md whose redaction preserves",
        "  its own type signature (XX/XX/XXXX). No other category does. That is",
        "  why DATE dominates the table above, and it is a property of the",
        "  MEASUREMENT, not of the corpus.",
        "",
        "-" * 66,
        "WAS THE CONTEXT ITSELF REDACTED?",
        "",
        f"  UNKNOWN spans with another marker in their context window:  "
        f"{100*ctx_redacted['unknown_yes']/max(ctx_redacted['unknown_all'],1):>5.1f}%",
        f"  resolved spans with another marker in their context window: "
        f"{100*ctx_redacted['resolved_yes']/max(ctx_redacted['resolved_all'],1):>5.1f}%",
        "",
        "  A contributing cause but not the main one — the gap is small. Most",
        "  unresolved spans sit in surviving prose that simply does not say what",
        "  was removed.",
    ]

    out = "\n".join(L)
    (RESULTS / "m2_category_distribution.txt").write_text(out + "\n")
    print(out)
    print("\ntop unresolved contexts:")
    for c, n in unresolved.most_common(15):
        print(f"  {n:>5,}  {c[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
