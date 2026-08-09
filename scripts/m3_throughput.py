"""
M3: what does it cost to redact a complaint?

WHY THIS METRIC AND NOT LATENCY ON A LAPTOP
-------------------------------------------
Earlier versions of this project measured milliseconds on an M1, inherited from a
premise decision 012 retired: the constraint is the company's trust boundary, not
a laptop, and a deployed redactor runs on whatever hardware sits inside that
boundary — in practice a cloud GPU.

So laptop latency is a real claim for exactly one arm, `micro`, where a small team
plausibly would run it locally. For `large` and the generative arm it is trivia:
nobody would deploy them that way, and the number answers no question anyone has.

What every arm needs answering is the portfolio's actual thesis:

    when should a small team call a frontier model, and when should they run
    their own small one?

That is a question about money, so this reports **cost per 1,000 complaints**.
Throughput is measured on the GPU because that is where a deployed redactor runs.

Reads:  models/<arm>/
        data/synthetic/injected_natural_v2_hard2.parquet
Writes: results/m3_throughput.csv
        results/m3_throughput.txt
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MODELS = ROOT / "models"
SYN = ROOT / "data" / "synthetic"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--gpu-hourly", type=float, default=0.099,
                    help="what the box actually costs, for the money column")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import m3_evaluate as M3
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    hw = torch.cuda.get_device_name(0) if dev.type == "cuda" else "Apple M1 (MPS)"
    texts = pd.read_parquet(SYN / "injected_natural_v2_hard2.parquet").head(args.n)["text"].tolist()

    rows = []
    for arm in ("micro", "base2", "large"):
        d = sorted(MODELS.glob(f"encoder-{arm}-s*"))
        if not d:
            continue
        d = d[0]
        tok = AutoTokenizer.from_pretrained(d)
        m = AutoModelForTokenClassification.from_pretrained(d, dtype=torch.float32).to(dev).eval()
        M3.predict_encoder(texts[:32], m, tok, dev)          # warm up
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.time()
        M3.predict_encoder(texts, m, tok, dev)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        el = time.time() - t0
        rate = len(texts) / el
        params = sum(p.numel() for p in m.parameters())
        size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
        rows.append({
            "arm": arm, "hardware": hw, "params": params,
            "size_mb_fp32": round(size_mb),
            "ms_per_complaint": round(1000 * el / len(texts), 1),
            "complaints_per_sec": round(rate, 1),
            "hours_per_300k": round(300_000 / rate / 3600, 2),
            "usd_per_1k_complaints": round(args.gpu_hourly * (1000 / rate) / 3600, 5),
        })
        print(f"  {arm:<8} {rate:7.1f}/sec  "
              f"${args.gpu_hourly*(1000/rate)/3600:.5f} per 1,000 complaints", flush=True)
        del m
        if dev.type == "cuda":
            torch.cuda.empty_cache()

    out = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULTS / "m3_throughput.csv", index=False)

    L = ["M3 — throughput and cost to redact", "=" * 72, "",
         f"hardware: {hw}   |   {len(texts):,} complaints   |   ${args.gpu_hourly}/hr", "",
         "Cost, not milliseconds, because the portfolio's question is when a small",
         "team should run their own model instead of calling a frontier one — and",
         "that is decided in dollars.", "",
         f"  {'arm':<8} {'params':>12} {'MB':>7} {'per sec':>9} {'hrs/300k':>10} {'$/1k':>10}"]
    for r in rows:
        L.append(f"  {r['arm']:<8} {r['params']:>12,} {r['size_mb_fp32']:>7} "
                 f"{r['complaints_per_sec']:>9.1f} {r['hours_per_300k']:>10.2f} "
                 f"{r['usd_per_1k_complaints']:>10.5f}")
    text = "\n".join(L)
    (RESULTS / "m3_throughput.txt").write_text(text + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
