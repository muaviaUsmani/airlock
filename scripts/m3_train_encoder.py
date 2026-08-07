"""
M3, branch A: fine-tune a small encoder to mark spans of personal information.

Per DECISIONS/006-model-architecture.md this is the first of two architectures.
It is a token classifier — DeBERTa-v3-base, ~184M parameters — tagging every
token with BIO labels over the 16 categories locked in DEFINITIONS.md.

WHY AN ENCODER CAN DO THIS AT ALL
---------------------------------
Marking which parts of a text are personal information is a per-token decision
with a fixed label set. That is exactly what a token classifier is built for: one
forward pass, one label per token, no generation. It cannot hallucinate text it
was not given, and its character offsets come from the tokenizer rather than from
the model's arithmetic — which is the failure mode that ruled out asking a small
generative model for JSON offsets.

WHAT IT IS TRAINED ON, AND WHY THAT IS DELICATE
-----------------------------------------------
Real CFPB text cannot be used: it contains XXXX where the personal information
was, so a model fitted to it learns "XXXX -> redact" and is worthless on real
text (M1). Training therefore happens on injected data, which brings its own
shortcut — the carrier sentences are formulaic, so a model can memorise PHRASING
instead of learning what personal information looks like.

Both leaks are handled in the data rather than here: disjoint narratives and
disjoint carrier templates, built by scripts/m2_inject.py. This script trains on
`injected_train` and never sees an evaluation narrative or an evaluation
template.

Runs on an M1 MacBook with no GPU, using MPS where available.

Reads:  data/synthetic/injected_train.parquet
Writes: models/airlock-encoder/
        results/m3_train_log.txt
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
MODELS = ROOT / "models"
RESULTS = ROOT / "results"

SEED = 20260806
BASE_MODEL = "microsoft/deberta-v3-base"
MAX_LEN = 384
BATCH = 8
GRAD_ACCUM = 2
EPOCHS = 3
LR = 3e-5
WARMUP = 0.06

CATEGORIES = [
    "PERSON", "ACCOUNT_ID", "GOV_ID", "CONTACT", "CASE_REF",
    "RELATIONSHIP", "LOCATION_FINE", "EMPLOYER", "LIFE_EVENT",
    "PROTECTED_ATTR", "HEALTH", "ORG_THIRD_PARTY",
    "AMOUNT", "DATE", "MERCHANT", "TEMPORAL",
]
LABELS = ["O"] + [f"{p}-{c}" for c in CATEGORIES for p in ("B", "I")]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class SpanDataset(Dataset):
    """
    Character spans -> BIO token labels, using the tokenizer's offset mapping.

    Offsets come from the tokenizer, never from arithmetic on our side. A token
    is labelled B- if it starts the span and I- if it merely overlaps it, and
    special tokens get -100 so they are ignored by the loss.
    """

    def __init__(self, df: pd.DataFrame, tokenizer, max_len: int = MAX_LEN):
        self.texts = df["text"].tolist()
        self.spans = df["spans"].tolist()
        self.tok = tokenizer
        self.max_len = max_len

    def __len__(self) -> int:
        return len(self.texts)

    def __getitem__(self, i: int):
        text = self.texts[i]
        enc = self.tok(
            text,
            truncation=True,
            max_length=self.max_len,
            return_offsets_mapping=True,
            padding="max_length",
        )
        offsets = enc["offset_mapping"]
        labels = []
        spans = sorted(self.spans[i], key=lambda s: s["start"])

        for idx, (s, e) in enumerate(offsets):
            if s == e:                      # special / padding token
                labels.append(-100)
                continue
            tag = "O"
            for sp in spans:
                if s < sp["end"] and sp["start"] < e:      # overlap
                    prefix = "B" if s <= sp["start"] else "I"
                    tag = f"{prefix}-{sp['category']}"
                    break
            labels.append(LABEL2ID[tag])

        return {
            "input_ids": torch.tensor(enc["input_ids"]),
            "attention_mask": torch.tensor(enc["attention_mask"]),
            "labels": torch.tensor(labels),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--limit", type=int, default=0, help="debug: cap training rows")
    ap.add_argument("--model", default=BASE_MODEL)
    args = ap.parse_args()

    from transformers import (AutoModelForTokenClassification, AutoTokenizer,
                              get_linear_schedule_with_warmup)

    torch.manual_seed(SEED)
    np.random.seed(SEED)

    train_path = SYN / "injected_train.parquet"
    if not train_path.exists():
        print(f"missing {train_path} — run scripts/m2_inject.py first")
        return 1

    df = pd.read_parquet(train_path)
    if args.limit:
        df = df.head(args.limit)

    dev = device()
    print(f"device: {dev}  |  model: {args.model}")
    print(f"training rows: {len(df):,}  |  labels: {len(LABELS)}\n")

    tok = AutoTokenizer.from_pretrained(args.model)
    # dtype=float32 is LOAD-BEARING, not a default being restated.
    #
    # transformers 5.x loads a checkpoint in the dtype it was SAVED in, and the
    # deberta-v3-base checkpoint on the Hub is stored in float16. Training a
    # pure-fp16 model with AdamW produces NaN on the very first optimiser step:
    # gradients are still finite after backward, then every parameter goes
    # non-finite after step(), because the fp16 update underflows against
    # AdamW's eps. Loss was exactly 4.8046875 — a giveaway, since that is
    # exactly representable in fp16.
    #
    # roberta-base happens to ship fp32 and trained fine on identical data,
    # which made this look like a DeBERTa or an MPS problem. It is neither: the
    # same NaN appears on CPU, with identical loss and gradient norm.
    model = AutoModelForTokenClassification.from_pretrained(
        args.model, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID,
        dtype=torch.float32,
    ).to(dev)
    assert next(model.parameters()).dtype == torch.float32, "model must train in fp32"


    ds = SpanDataset(df, tok)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=0)

    steps = math.ceil(len(dl) / GRAD_ACCUM) * args.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, int(steps * WARMUP), steps)

    log: list[str] = [
        "M3 branch A — encoder training log",
        "=" * 58,
        f"base model      {args.model}",
        f"parameters      {sum(p.numel() for p in model.parameters()):,}",
        f"device          {dev}",
        f"training rows   {len(df):,}",
        f"epochs          {args.epochs}   batch {args.batch} x{GRAD_ACCUM} accum",
        f"lr              {LR}   warmup {WARMUP}",
        f"max seq length  {MAX_LEN}",
        f"seed            {SEED}",
        "",
    ]

    model.train()
    t_start = time.time()
    for epoch in range(args.epochs):
        running, seen, t0 = 0.0, 0, time.time()
        opt.zero_grad()
        for step, batch in enumerate(dl):
            batch = {k: v.to(dev) for k, v in batch.items()}
            out = model(**batch)
            (out.loss / GRAD_ACCUM).backward()
            running += out.loss.item()
            seen += 1
            if (step + 1) % GRAD_ACCUM == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
            if seen % 200 == 0:
                rate = seen * args.batch / (time.time() - t0)
                done = seen / len(dl)
                eta = (time.time() - t0) * (1 - done) / max(done, 1e-9)
                print(f"  epoch {epoch+1} {100*done:5.1f}%  loss {running/seen:.4f}  "
                      f"{rate:5.1f} ex/s  eta {eta/60:5.1f}m", flush=True)
        line = f"epoch {epoch+1}: mean loss {running/max(seen,1):.4f}  ({(time.time()-t0)/60:.1f} min)"
        print("  " + line, flush=True)
        log.append(line)

    total_min = (time.time() - t_start) / 60
    out_dir = MODELS / "airlock-encoder"
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    (out_dir / "labels.json").write_text(json.dumps({"labels": LABELS}, indent=2))

    size_mb = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file()) / 1e6
    log += ["", f"total training time  {total_min:.1f} min",
            f"model on disk        {size_mb:.0f} MB",
            f"saved to             {out_dir.relative_to(ROOT)}"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "m3_train_log.txt").write_text("\n".join(log) + "\n")
    print("\n".join(log[-4:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
