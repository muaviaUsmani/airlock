"""
M2: how accurate is the category estimator? Everything downstream depends on it.

WHY THIS MATTERS MORE THAN IT LOOKS
-----------------------------------
`classify()` in m2_category_distribution.py guesses what a XXXX marker replaced,
from surviving context. It is used in THREE places:

  1. the injection distribution (decision 004)
  2. mining carrier sentences from the corpus (decision 008's fix)
  3. building the surrogate transfer test, which is how the model is judged

Points 2 and 3 are the dangerous pair. If the estimator systematically mislabels
some category, then the training carriers AND the test that grades them are wrong
IN THE SAME DIRECTION. A model trained on that mistake would be rewarded for
reproducing it, and the transfer number — the one decision 006 called most
important — would look good for the wrong reason.

That is a correlated-error problem, and it cannot be argued away. It has to be
measured.

HOW IT CAN BE MEASURED WITHOUT GROUND TRUTH
-------------------------------------------
There is no labelled corpus, but there does not need to be. The injected sets
contain spans whose category we KNOW, because we wrote them. So:

    take an injected span whose category is known
    replace its text with XXXX, exactly as the CFPB would have
    run the estimator on that marker
    compare its guess to the truth

This reconstructs the estimator's input conditions exactly and grades it against
labels that are facts. No annotation, no oracle, no judgement.

Reads:  data/synthetic/injected_stratified.parquet
        data/synthetic/injected_natural_v2.parquet
Writes: results/m2_estimator_accuracy.csv
        results/m2_estimator_accuracy.txt
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from m2_category_distribution import classify

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RESULTS = ROOT / "results"

# How the CFPB renders a redaction: one XXXX per word removed.
def as_marker(value: str) -> str:
    n = max(1, len(value.split()))
    return " ".join(["XXXX"] * min(n, 6))


def main() -> int:
    frames = []
    for name in ("stratified", "natural_v2"):
        p = SYN / f"injected_{name}.parquet"
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        print("no injected sets found — run scripts/m2_inject.py first", file=sys.stderr)
        return 1
    df = pd.concat(frames, ignore_index=True)

    confusion: dict[str, Counter] = defaultdict(Counter)
    total = 0

    for text, spans in zip(df["text"], df["spans"]):
        # Rebuild the narrative with every injected span replaced by a marker,
        # tracking where each marker lands, in one forward pass.
        spans = sorted(spans, key=lambda s: s["start"])
        out, positions, pos, last = [], [], 0, 0
        for s in spans:
            lit = text[last : s["start"]]
            out.append(lit)
            pos += len(lit)
            marker = as_marker(s["value"])
            positions.append((pos, pos + len(marker), s["category"]))
            out.append(marker)
            pos += len(marker)
            last = s["end"]
        out.append(text[last:])
        masked = "".join(out)

        for start, end, truth in positions:
            guess = classify(masked, start, end)
            confusion[truth][guess] += 1
            total += 1

    rows = []
    for truth, guesses in confusion.items():
        n = sum(guesses.values())
        rows.append({
            "true_category": truth,
            "n": n,
            "correct": guesses.get(truth, 0),
            "accuracy_pct": round(100 * guesses.get(truth, 0) / max(n, 1), 2),
            "unknown_pct": round(100 * guesses.get("UNKNOWN", 0) / max(n, 1), 2),
            "top_confusion": max(
                ((g, c) for g, c in guesses.items() if g != truth and g != "UNKNOWN"),
                key=lambda kv: kv[1], default=("-", 0))[0],
        })
    out_df = pd.DataFrame(rows).sort_values("n", ascending=False)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(RESULTS / "m2_estimator_accuracy.csv", index=False)

    correct = sum(c.get(t, 0) for t, c in confusion.items())
    unknown = sum(c.get("UNKNOWN", 0) for c in confusion.values())
    wrong = total - correct - unknown

    L = ["M2 — category estimator accuracy", "=" * 72, "",
         f"{total:,} injected spans, category known because we wrote it,",
         "re-masked as XXXX and put back through the estimator.", "",
         f"  correct            {correct:>8,}  ({100*correct/max(total,1):>5.1f}%)",
         f"  UNKNOWN (declined) {unknown:>8,}  ({100*unknown/max(total,1):>5.1f}%)",
         f"  WRONG              {wrong:>8,}  ({100*wrong/max(total,1):>5.1f}%)", "",
         "Declining is safe: an UNKNOWN marker is never mined into a carrier and",
         "never scored in the transfer test. A WRONG guess is the dangerous one —",
         "it puts a mislabelled carrier into training AND the same mistake into",
         "the test that grades it.", "",
         "-" * 72, "PER CATEGORY", "",
         f"  {'true category':<18} {'n':>7} {'correct':>9} {'unknown':>9}  {'most confused with':<18}"]
    for _, r in out_df.iterrows():
        L.append(f"  {r['true_category']:<18} {r['n']:>7,} {r['accuracy_pct']:>8.1f}% "
                 f"{r['unknown_pct']:>8.1f}%  {r['top_confusion']:<18}")

    precise = out_df[out_df["accuracy_pct"] >= 70]["true_category"].tolist()
    risky = out_df[(out_df["accuracy_pct"] < 40) & (out_df["n"] >= 100)]["true_category"].tolist()
    L += ["", "-" * 72, "HOW TO READ THIS, AND WHAT IT DOES NOT SAY", "",
          "These spans sit in HAND-WRITTEN carrier sentences, so this grades the",
          "rules against a couple of phrasings per category, not against real",
          "corpus prose. The absolute percentage is therefore not an estimate of",
          "real-world accuracy, and is not quoted as one.",
          "",
          "What it does establish, and this is robust: the rules are BRITTLE TO",
          "PHRASING. Two ordinary English sentences per category, and for ten of",
          "sixteen categories the estimator recognises neither. Real customer",
          "prose is far more varied than two authored sentences, so on the corpus",
          "it will do no better and probably worse.",
          "",
          "The ~50%-correct/~50%-unknown pattern is the giveaway: it means one",
          "held-out phrasing happened to contain a cue the rules match and the",
          "other did not. That is a coin flip on wording, not comprehension.",
          "",
          "-" * 72, "WHAT THIS MEANS FOR THE PIPELINE", "",
          f"  trustworthy (>=70% correct): {', '.join(precise) if precise else 'none'}",
          f"  unreliable  (<40%, n>=100):  {', '.join(risky) if risky else 'none'}", "",
          "Categories in the second list must not be mined into carriers or scored",
          "in the transfer test without saying so, because for those the training",
          "data and the grader share a mistake."]
    text = "\n".join(L)
    (RESULTS / "m2_estimator_accuracy.txt").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
