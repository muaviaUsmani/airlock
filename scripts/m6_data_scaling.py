"""M6 — accuracy against training-set size, per arm.

Companion to m6_data_scaling.sh. Scores every arm at every training size on the
M3 HEADLINE set (the surrogate transfer set), so the curve is directly
comparable to the published number rather than to an easier proxy.

Reading the output
------------------
The question is whether the larger arms were starved at 15,000 examples. Compare
each arm's gain from 5k -> 15k:

  large still climbing steeply  -> starved; the M3 comparison is premature and
                                   the honest headline is "at this data budget"
  large as flat as micro        -> saturated; more data would not change the
                                   ranking, and DECISIONS/015's memorisation
                                   account is the whole story

A curve that is still rising at its last point cannot be used to claim a model
has been given its best shot -- which is exactly why this is measured rather
than argued.

Writes: results/m6_data_scaling.txt
        results/m6_data_scaling.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import m3_evaluate as M3  # noqa: E402

MODELS = ROOT / "models"
RESULTS = ROOT / "results"
FULL_N = 14995  # rows in injected_train_hard2 -- the "15k" point
SEED = "20260806"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="micro,base2,large")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer
    import m3_transfer_surrogate as TS

    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device: {dev}", flush=True)

    df_s = TS.build_set(TS.N)
    texts = df_s["text"].tolist()
    truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df_s["spans"]]
    unfilled = df_s["unfilled"].tolist()
    print(f"headline set: {len(texts):,} narratives, "
          f"{sum(len(t) for t in truths):,} spans\n", flush=True)

    def clean(preds):
        return [[sp for sp in p if not any(sp[0] < ue and us < sp[1] for us, ue in unf)]
                for p, unf in zip(preds, unfilled)]

    rows = []
    for arm in [a for a in args.arms.split(",") if a]:
        # The sized runs, plus the existing full-data run at the same seed.
        cands = [(int(re.search(r"-n(\d+)-", d.name).group(1)), d)
                 for d in MODELS.glob(f"encoder-{arm}-n*-s{SEED}")]
        full = MODELS / f"encoder-{arm}-s{SEED}"
        if (full / "model.safetensors").exists():
            cands.append((FULL_N, full))
        for n, d in sorted(cands):
            if not (d / "model.safetensors").exists():
                print(f"  SKIP {d.name}: no weights", file=sys.stderr)
                continue
            tok = AutoTokenizer.from_pretrained(d)
            mod = AutoModelForTokenClassification.from_pretrained(
                d, dtype=torch.float32).to(dev).eval()
            r = M3.score(truths, clean(M3.predict_encoder(texts, mod, tok, dev)),
                         want_category=True)
            rows.append({"arm": arm, "train_rows": n, "model": d.name,
                         "recall_pct": round(100 * r["recall"], 2),
                         "precision_pct": round(100 * r["precision"], 2),
                         "f1_pct": round(100 * r["f1"], 2)})
            print(f"  {arm:<7} n={n:<6} f1 {100*r['f1']:5.1f}%  "
                  f"recall {100*r['recall']:5.1f}%", flush=True)
            del mod

    if not rows:
        print("nothing scored", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "m6_data_scaling.csv", index=False)

    sizes = sorted(df.train_rows.unique())
    L = ["M6 — accuracy against training-set size", "=" * 74, "",
         f"F1 % on the M3 headline set (surrogate), seed {SEED} throughout.",
         "One seed per point: this measures the SHAPE of each curve, not the",
         "seed variance already reported in m3_arms.txt.", "",
         f"  {'arm':<8}" + "".join(f"{('n=' + format(s, ',')):>12}" for s in sizes)
         + f"{'gain 5k->15k':>14}"]
    for arm in df.arm.unique():
        sub = df[df.arm == arm].set_index("train_rows").f1_pct
        cells = "".join(f"{sub[s]:>12.1f}" if s in sub.index else f"{'-':>12}"
                        for s in sizes)
        gain = (sub[FULL_N] - sub[5000]) if (FULL_N in sub.index and 5000 in sub.index) else float("nan")
        L.append(f"  {arm:<8}{cells}{gain:>13.1f}")

    L += ["", "-" * 74, "READING IT", ""]
    try:
        g = {a: (df[(df.arm == a) & (df.train_rows == FULL_N)].f1_pct.iloc[0]
                 - df[(df.arm == a) & (df.train_rows == 5000)].f1_pct.iloc[0])
             for a in df.arm.unique()}
        big = max((a for a in g if a != "micro"), key=lambda a: g[a]) if len(g) > 1 else None
        if big:
            L += [f"  From 5k to 15k rows: micro gains {g['micro']:+.1f} F1, "
                  f"{big} gains {g[big]:+.1f}.", ""]
            if g[big] - g.get("micro", 0) > 2.0:
                L += ["  The larger arm is still climbing when micro has levelled off.",
                      "  It was STARVED at 15k, so the M3 comparison is made at a data",
                      "  budget that favours the smaller model. The headline should say",
                      "  'at 15,000 examples' rather than stating a general result."]
            else:
                L += ["  Both curves have flattened by 15k. The larger arm was NOT",
                      "  starved -- more data of this kind would not close the gap, and",
                      "  the memorisation account in DECISIONS/015 is the explanation,",
                      "  not a data budget artefact."]
    except (IndexError, KeyError):
        L += ["  (not all points available)"]

    text = "\n".join(L)
    (RESULTS / "m6_data_scaling.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
