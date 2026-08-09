"""M3 — what does the writer actually cost, given equal engineering effort?

WHY THIS EXISTS
---------------
The published writer row says 3,590 ms/narrative against micro's 4.5 ms, a 690x
gap presented as architectural. That framing is not safe yet.

The same code measured 11,400 ms/narrative earlier on 2026-08-09, before length
bucketing; one afternoon's work moved it 9x. A comparison between an encoder
that got attention and a writer that did not measures attention, not
architecture. HANDOFF §5 already caught this for the writer's TRAINING cost --
"40% of compute went to padding, gradient checkpointing was on with 17GB of VRAM
free, batch was 2" -- and the same disease is present on the inference side.

So this measures the existing writer under progressively fairer configurations,
and -- the part that makes it honest -- CHECKS THAT THE OUTPUT DID NOT CHANGE.
A speedup that quietly costs accuracy is not a speedup, and dtype changes are
exactly the kind of thing that can move generated text.

The model was TRAINED in bf16 (see results/m3_train_log_generative-*.txt); the
evaluation loads it in fp32. Upcasting a bf16 checkpoint adds no precision, so
bf16 inference is arguably the more faithful configuration as well as the faster
one.

Writes: results/m3_writer_cost.txt
        results/m3_writer_cost.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import m3_evaluate as M3  # noqa: E402
import m3_predict_generative as GEN  # noqa: E402

RESULTS = ROOT / "results"

# (label, dtype, batch, bucket)
CONFIGS = [
    ("fp32 b12 bucketed (published)", "float32", 12, True),
    ("bf16 b12 bucketed", "bfloat16", 12, True),
    ("bf16 b32 bucketed", "bfloat16", 32, True),
    ("bf16 b64 bucketed", "bfloat16", 64, True),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--writer", default="models/generative-s20260806")
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import m3_transfer_surrogate as TS
    from m3_train_generative import INSTRUCTION

    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device: {dev}", flush=True)

    # Same construction as the headline, truncated to --n so configs are
    # compared on identical text.
    df = TS.build_set(TS.N).head(args.n)
    texts = df["text"].tolist()
    truths = [[(s["start"], s["end"], s["category"]) for s in sp] for sp in df["spans"]]
    unfilled = df["unfilled"].tolist()

    def clean(preds):
        return [[sp for sp in p if not any(sp[0] < ue and us < sp[1] for us, ue in unf)]
                for p, unf in zip(preds, unfilled)]

    print(f"{len(texts):,} narratives, {sum(len(t) for t in truths):,} spans\n", flush=True)

    wdir = ROOT / args.writer
    wtok = AutoTokenizer.from_pretrained(wdir)
    if wtok.pad_token is None:
        wtok.pad_token = wtok.eos_token
    cfg = json.loads((wdir / "checkpoint.json").read_text())

    rows, baseline_preds = [], None
    for label, dtype_name, batch, bucket in CONFIGS:
        dtype = getattr(torch, dtype_name)
        base = AutoModelForCausalLM.from_pretrained(cfg["base_model"], dtype=dtype).to(dev)
        mod = PeftModel.from_pretrained(base, wdir).to(dev).eval()

        if dev.type == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        preds, stats = GEN.predict(texts, mod, wtok, dev, INSTRUCTION,
                                   batch=batch, bucket=bucket)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        secs = time.time() - t0
        peak = (torch.cuda.max_memory_allocated() / 1e9) if dev.type == "cuda" else float("nan")

        r = M3.score(truths, clean(preds), want_category=True)
        ms = 1000 * secs / max(len(texts), 1)

        # Did the faster configuration change what the model produced?
        if baseline_preds is None:
            baseline_preds = preds
            identical = "(baseline)"
        else:
            same = sum(1 for a, b in zip(baseline_preds, preds) if a == b)
            identical = f"{100*same/len(preds):.1f}% identical"

        rows.append({"config": label, "dtype": dtype_name, "batch": batch,
                     "ms_per_narrative": round(ms, 1),
                     "f1_pct": round(100 * r["f1"], 2),
                     "recall_pct": round(100 * r["recall"], 2),
                     "precision_pct": round(100 * r["precision"], 2),
                     "unparseable_pct": round(100 * stats["unparseable_rate"], 2),
                     "peak_vram_gb": round(peak, 2),
                     "vs_baseline": identical})
        print(f"  {label:<32} {ms:8.0f} ms/narr  f1 {100*r['f1']:5.1f}%  "
              f"unparseable {100*stats['unparseable_rate']:5.1f}%  "
              f"vram {peak:4.1f}GB  {identical}", flush=True)
        del mod, base
        if dev.type == "cuda":
            torch.cuda.empty_cache()

    df_out = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(RESULTS / "m3_writer_cost.csv", index=False)

    best = min(rows, key=lambda r: r["ms_per_narrative"])
    pub = rows[0]
    L = ["M3 — the writer's inference cost under equal effort", "=" * 76, "",
         f"{len(texts):,} narratives from the M3 headline set, same text for every row.",
         "F1 and unparseable rate are reported alongside speed so a configuration",
         "that bought time with accuracy cannot pass as a free win.", "",
         f"  {'configuration':<32}{'ms/narr':>10}{'f1':>8}{'unparse':>9}{'VRAM':>7}  vs baseline"]
    for r in rows:
        L.append(f"  {r['config']:<32}{r['ms_per_narrative']:>10.0f}{r['f1_pct']:>8.1f}"
                 f"{r['unparseable_pct']:>8.1f}%{r['peak_vram_gb']:>6.1f}G  {r['vs_baseline']}")
    speedup = pub["ms_per_narrative"] / max(best["ms_per_narrative"], 1e-9)
    L += ["", "-" * 76, "",
          f"  best configuration is {speedup:.1f}x faster than the published one,",
          f"  at {best['ms_per_narrative']:.0f} ms/narrative against micro's 4.5 ms",
          f"  -- a gap of {best['ms_per_narrative']/4.5:.0f}x, not the 690x the",
          "  published row implies.", "",
          "  NOT measured here: a serving runtime (vLLM/TensorRT-LLM), which the",
          "  literature puts at a further 5-10x, and the span-emitting formulation",
          "  in DECISIONS/016, which would cut decode tokens ~13x. Both are",
          "  predictions and neither belongs in a published number until run."]
    text = "\n".join(L)
    (RESULTS / "m3_writer_cost.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
