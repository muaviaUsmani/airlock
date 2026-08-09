"""M6 — one epoch versus three, per arm, on the M3 headline set.

Companion to m6_epoch_ablation.sh. The question is whether the M3 size ranking
survives when the larger arms are not trained past their own optimum.

m3_train_encoder.py trains a fixed 3 epochs with no validation split and keeps
the last checkpoint. At 15k rows `large` reaches training loss 0.0006 by epoch 2
and `micro` only 0.0095 by epoch 3, so the arms are compared at different points
on their own overfitting curves. Retraining every arm for exactly one epoch,
changing nothing else, isolates that.

  large improves a lot, micro flat or worse  -> the ranking was an artefact of
                                                the fixed schedule; the headline
                                                is about our recipe
  ranking unchanged                          -> capacity really is not helping
                                                on this task, and DECISIONS/015
                                                stands as written

Writes: results/m6_epoch_ablation.txt
        results/m6_epoch_ablation.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import m3_evaluate as M3  # noqa: E402

MODELS = ROOT / "models"
RESULTS = ROOT / "results"
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

    def clean(preds):
        return [[sp for sp in p if not any(sp[0] < ue and us < sp[1] for us, ue in unf)]
                for p, unf in zip(preds, unfilled)]

    print(f"headline set: {len(texts):,} narratives, "
          f"{sum(len(t) for t in truths):,} spans\n", flush=True)

    rows = []
    for arm in [a for a in args.arms.split(",") if a]:
        for epochs, d in ((1, MODELS / f"encoder-{arm}-e1-s{SEED}"),
                          (3, MODELS / f"encoder-{arm}-s{SEED}")):
            if not (d / "model.safetensors").exists():
                print(f"  SKIP {d.name}: no weights", file=sys.stderr)
                continue
            tok = AutoTokenizer.from_pretrained(d)
            mod = AutoModelForTokenClassification.from_pretrained(
                d, dtype=torch.float32).to(dev).eval()
            r = M3.score(truths, clean(M3.predict_encoder(texts, mod, tok, dev)),
                         want_category=True)
            rows.append({"arm": arm, "epochs": epochs,
                         "recall_pct": round(100 * r["recall"], 2),
                         "precision_pct": round(100 * r["precision"], 2),
                         "f1_pct": round(100 * r["f1"], 2)})
            print(f"  {arm:<7} {epochs} epoch(s)  f1 {100*r['f1']:5.1f}%  "
                  f"recall {100*r['recall']:5.1f}%", flush=True)
            del mod

    if not rows:
        print("nothing scored", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "m6_epoch_ablation.csv", index=False)

    L = ["M6 — one epoch versus three", "=" * 70, "",
         f"F1 % on the M3 headline set (surrogate), seed {SEED}, 15k rows.",
         "Only the epoch count differs. Single seed per cell: this measures",
         "direction, not the seed variance already in m3_arms.txt.", "",
         f"  {'arm':<8}{'1 epoch':>11}{'3 epochs':>11}{'delta':>9}"]
    best1 = best3 = None
    for arm in df.arm.unique():
        sub = df[df.arm == arm].set_index("epochs").f1_pct
        a = sub.get(1, float("nan"))
        b = sub.get(3, float("nan"))
        L.append(f"  {arm:<8}{a:>11.1f}{b:>11.1f}{a-b:>+9.1f}")
        if best1 is None or a > best1[1]:
            best1 = (arm, a)
        if best3 is None or b > best3[1]:
            best3 = (arm, b)

    L += ["", "-" * 70, "READING IT", ""]
    if best1 and best3:
        L += [f"  best at 3 epochs: {best3[0]} ({best3[1]:.1f})",
              f"  best at 1 epoch:  {best1[0]} ({best1[1]:.1f})", ""]
        if best1[0] != best3[0]:
            L += ["  THE RANKING CHANGES. The M3 headline ordering is a property of",
                  "  the fixed 3-epoch schedule, not of model capacity. Any claim that",
                  "  a smaller model wins must be restated as a claim about this",
                  "  training recipe, and the recipe needs per-arm early stopping",
                  "  before the comparison means anything."]
        else:
            L += ["  The ranking holds. Training the larger arms less does not rescue",
                  "  them, so the fixed schedule is not what produced the result and",
                  "  DECISIONS/015's memorisation account stands.",
                  "",
                  "  Note this does NOT clear the recipe entirely: learning rate is",
                  "  still 3e-5 for every arm and is not even a CLI argument. A rate",
                  "  tuned per scale is a separate, untested lever."]
    text = "\n".join(L)
    (RESULTS / "m6_epoch_ablation.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
