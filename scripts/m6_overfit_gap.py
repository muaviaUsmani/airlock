"""M6 — is micro's win real, or does capacity buy memorisation?

THE HYPOTHESIS BEING TESTED
---------------------------
The M3 headline is that the 70.7M encoder beats the 434M one by ~5 F1, which is
the opposite of the prediction. HANDOFF section 4 offers two candidate
explanations and establishes neither:

  (a) 15,000 examples underdetermine 434M parameters, or
  (b) the larger models overfit the INJECTED distribution and transfer worse.

This script tests (b), using the diagnostic the project pre-registered for
exactly this purpose in docs/04-model.md:

  > the `seen_templates` control set -- the same evaluation narratives rendered
  > with TRAINING templates. A model that scores well on `seen_templates` and
  > badly on `stratified` has memorised phrasing.

So each arm is scored along a four-point transfer curve, easiest to hardest:

  1. seen_templates_hard2  training phrasings          in-distribution
  2. stratified_hard2      held-out carrier phrasings  same injector, new templates
  3. natural_v2_hard2      held-out injector           synthetic carriers still
  4. surrogate set         the M3 HEADLINE set         real prose, no carriers

Point 4 is the one the headline quotes, and it is much harder than point 3:
micro scores 95.4% on the raw natural_v2_hard2 parquet and 85.5% on the
surrogate set. A curve that stopped at point 3 would miss the transfer story.

WHAT WOULD CONFIRM OVERFITTING
------------------------------
Overfitting is a claim about the SHAPE of that curve, not its height. If `large`
memorised training phrasing, it should look good at step 1 and lose more than
`micro` does by the end -- a steeper decline. If instead every arm declines in
parallel and `large` is simply lower everywhere, the problem is not overfitting;
it is that the larger model never learned the task as well in the first place,
which points at (a) or at the training recipe.

Reporting the drop in PERCENTAGE POINTS OF F1 rather than as a ratio, because
the arms start from different heights and a ratio would flatter whichever arm
starts lowest.

Usage: m6_overfit_gap.py [--n 4000] [--arms micro,base2,large]
Writes: results/m6_overfit_gap.txt
        results/m6_overfit_gap.csv
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import m3_evaluate as M3  # noqa: E402

SYN = ROOT / "data" / "synthetic"
MODELS = ROOT / "models"
RESULTS = ROOT / "results"

# Ordered easiest -> hardest. The order is the point: it is a transfer curve.
#
# The fourth entry is not a parquet. It is the surrogate set built by
# m3_transfer_surrogate, which is what the M3 headline actually scores -- real
# CFPB prose with real redaction sites refilled with plausible surrogates, and
# no carrier templates from any injector. Including it matters: micro scores
# 95.4% on the raw natural_v2_hard2 parquet and 85.5% on the surrogate set, so a
# curve that stopped at the parquet would miss the entire transfer story.
SETS = [
    ("seen_templates_hard2", "training phrasings (in-distribution)"),
    ("stratified_hard2", "held-out phrasings (same injector)"),
    ("natural_v2_hard2", "held-out injector, synthetic carriers"),
    ("__surrogate__", "M3 headline set: real prose, no carriers"),
]


def _identity(preds):
    return preds


def load_set(name: str, n: int):
    """Return (texts, truths, clean) for one point on the transfer curve.

    `clean` exists because the surrogate set contains markers whose category
    could not be estimated; a prediction touching one is unknowable either way,
    so m3_compare_arms drops it. Scoring the surrogate set WITHOUT that filter
    would not reproduce the published headline.
    """
    if name == "__surrogate__":
        import m3_transfer_surrogate as TS
        # Honour --n here too. It used to build the full set regardless, so a
        # "--n 60 wiring check" still scored 2,492 narratives against nine arms
        # and took the best part of an hour -- a smoke test that is not smoke.
        df = TS.build_set(TS.N if n >= TS.N else n)
        texts = df["text"].tolist()
        truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df["spans"]]
        unfilled = df["unfilled"].tolist()

        def clean(preds):
            return [[sp for sp in p if not any(sp[0] < ue and us < sp[1] for us, ue in unf)]
                    for p, unf in zip(preds, unfilled)]

        return texts, truths, clean

    df = pd.read_parquet(SYN / f"injected_{name}.parquet").head(n)
    texts = df["text"].tolist()
    truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df["spans"]]
    return texts, truths, _identity


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--arms", default="micro,base2,large")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    # cuda first: a sibling script checked only mps and silently ran on CPU.
    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device: {dev}", flush=True)

    data = {}
    for key, _ in SETS:
        t, y, c = load_set(key, args.n)
        data[key] = (t, y, c)
        print(f"  {key:24} {len(t):,} narratives, {sum(len(s) for s in y):,} spans", flush=True)

    rows = []
    for arm in [a for a in args.arms.split(",") if a]:
        for d in sorted(MODELS.glob(f"encoder-{arm}-s*")):
            if not (d / "model.safetensors").exists():
                print(f"  SKIP {d.name}: no weights", file=sys.stderr)
                continue
            tok = AutoTokenizer.from_pretrained(d)
            mod = AutoModelForTokenClassification.from_pretrained(
                d, dtype=torch.float32).to(dev).eval()
            seed = d.name.split("-s")[-1]
            for key, _ in SETS:
                texts, truths, clean = data[key]
                t0 = time.time()
                r = M3.score(truths, clean(M3.predict_encoder(texts, mod, tok, dev)),
                             want_category=True)
                rows.append({"arm": arm, "seed": seed, "set": key,
                             "recall_pct": round(100 * r["recall"], 2),
                             "precision_pct": round(100 * r["precision"], 2),
                             "f1_pct": round(100 * r["f1"], 2),
                             "seconds": round(time.time() - t0, 1)})
                print(f"  {arm:<7} s{seed} {key:24} "
                      f"f1 {100*r['f1']:5.1f}%  recall {100*r['recall']:5.1f}%", flush=True)
            del mod

    if not rows:
        print("no arms scored -- no weights available", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "m6_overfit_gap.csv", index=False)

    def agg(arm, key):
        v = df[(df.arm == arm) & (df["set"] == key)].f1_pct.tolist()
        if not v:
            return None, None
        return st.mean(v), (st.stdev(v) if len(v) > 1 else 0.0)

    arms = [a for a in df.arm.unique()]
    L = ["M6 — does capacity buy memorisation?", "=" * 78, "",
         f"{args.n:,} narratives per set, three seeds per arm, F1 %.", "",
         "A transfer curve, easiest to hardest. Overfitting is a claim about the",
         "SHAPE of this curve: a memorising model starts high and falls further.", "",
         f"  {'arm':<8}" + "".join(f"{lbl[:16]:>18}" for _, lbl in
                                     [(k, k.strip('_').split('_')[0]) for k, _ in SETS])
         + f"{'drop 1->4':>12}"]
    for arm in arms:
        cells, first, last = "", None, None
        for key, _ in SETS:
            m, s = agg(arm, key)
            if m is None:
                cells += f"{'-':>18}"
                continue
            cells += f"{m:>12.1f} ±{s:<4.1f}"
            if first is None:
                first = m
            last = m
        drop = (first - last) if (first is not None and last is not None) else float("nan")
        L.append(f"  {arm:<8}{cells}{drop:>11.1f}")

    L += ["", "-" * 78, "READING IT", ""]
    drops = {a: (agg(a, SETS[0][0])[0] or 0) - (agg(a, SETS[-1][0])[0] or 0) for a in arms}
    if "micro" in drops and len(drops) > 1:
        worst = max((a for a in drops if a != "micro"), key=lambda a: drops[a])
        diff = drops[worst] - drops["micro"]
        L += [f"  micro loses {drops['micro']:.1f} F1 points across the curve;",
              f"  {worst} loses {drops[worst]:.1f}.  Difference: {diff:+.1f} points.", ""]
        if diff > 3.0:
            L += ["  The larger arm falls FURTHER. That is the overfitting signature:",
                  "  it holds up on training phrasings and gives more of it back on",
                  "  unseen ones. Hypothesis (b) is supported."]
        elif diff < -3.0:
            L += ["  The larger arm falls LESS. Overfitting to phrasing is contradicted;",
                  "  the larger arm is simply worse everywhere, which points at",
                  "  hypothesis (a) or at the training recipe, not at memorisation."]
        else:
            L += ["  The curves decline in PARALLEL (difference within ±3 points).",
                  "  Overfitting to the injected phrasing is NOT what separates these",
                  "  arms -- the larger model is lower everywhere, including on the",
                  "  training distribution it is supposed to have memorised.",
                  "  Hypothesis (b) is not supported; (a) remains open."]
    L += ["", "  Note: this tests transfer across CARRIER PHRASING. It does not test",
          "  hypothesis (a) -- whether 15,000 examples underdetermine 434M",
          "  parameters -- which needs a training-set-size sweep, not an eval."]

    text = "\n".join(L)
    (RESULTS / "m6_overfit_gap.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
