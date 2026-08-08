"""
M3, branch B: a small generative model that tags personal information inline.

This is the brief's open fork #1, and it has been closed and reopened once.
[Decision 009](../DECISIONS/009-dropping-the-generative-branch.md) dropped it on
one number — 4-5 seconds per narrative at inference on an M1, which meant weeks
of wall-clock for a bank's complaint volume. Its own closing paragraph said to
reopen it if the premise ever allowed a GPU at inference.

[Decision 012](../DECISIONS/012-the-premise-is-a-trust-boundary-not-a-laptop.md)
did exactly that: the constraint is the company's trust boundary, not a laptop,
and inside that boundary a GPU is ordinary. On one, 4-5 seconds becomes ~50-100ms
and the objection evaporates.

WHY THIS IS NOT THE SAME EXPERIMENT AS "A BIGGER ENCODER"
--------------------------------------------------------
Scaling the encoder to deberta-v3-large (434M) tests capacity. This tests
ARCHITECTURE, and the two cannot substitute for each other:

  - an encoder physically cannot alter the text; a generative model can, and how
    often it does is a result rather than a bug to hide
  - an encoder learns an arbitrary label index from examples. A generative model
    is asked in language for <PERSON>...</PERSON>, so it can lean on what it
    already knows a person is. That should matter most for HEALTH (3 examples in
    the real-prose test) and RELATIONSHIP (16), where no classifier can learn
    much from that little

At 0.6B against large's 434M this is also close to a SIZE-MATCHED comparison,
which is a far cleaner test of "does architecture matter" than 184M vs 600M.

OUTPUT FORMAT: INLINE TAGS
--------------------------
Chosen in decision 006 over two alternatives, both documented there. The model
rewrites the narrative with markup:

    I called <PERSON>Sarah Mendez</PERSON> at the <LOCATION_FINE>Fremont</...>

Spans are recovered by aligning output to input. The risk is text drift — a
generative model can silently reword what it is not tagging — so the harness
VERIFIES the untagged content against the input and reports drift as a failure
mode of the architecture rather than repairing it. A harness that quietly fixes
drift hides the thing being measured.

Reads:  data/synthetic/injected_train_hard2.parquet
Writes: models/<out>/
        results/m3_train_log_<out>.txt
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
MODELS = ROOT / "models"
RESULTS = ROOT / "results"

SEED = 20260806
BASE_MODEL = "Qwen/Qwen3-0.6B"
MAX_LEN = 1024
BATCH = 2
GRAD_ACCUM = 8
EPOCHS = 2
LR = 1e-4
LORA_R = 16
LORA_ALPHA = 32

INSTRUCTION = (
    "Mark every piece of personal information in the complaint below by wrapping "
    "it in tags, and change nothing else. Use these tags exactly:\n"
    "<PERSON>, <ACCOUNT_ID>, <GOV_ID>, <CONTACT>, <CASE_REF>, <RELATIONSHIP>, "
    "<LOCATION_FINE>, <EMPLOYER>, <LIFE_EVENT>, <PROTECTED_ATTR>, <HEALTH>, "
    "<ORG_THIRD_PARTY>, <AMOUNT>, <DATE>, <MERCHANT>, <TEMPORAL>.\n"
    "Do not tag the company the complaint is filed against, plain counts, credit "
    "scores, interest rates, or regulation citations.\n\n"
    "Complaint:\n"
)


def tag_text(text: str, spans: list[dict]) -> str:
    """Build the target: the same text with spans wrapped, nothing else changed."""
    out, last = [], 0
    for s in sorted(spans, key=lambda x: x["start"]):
        out.append(text[last : s["start"]])
        out.append(f"<{s['category']}>{s['value']}</{s['category']}>")
        last = s["end"]
    out.append(text[last:])
    return "".join(out)


class TagDataset(Dataset):
    """Prompt + tagged completion, with the prompt masked out of the loss."""

    def __init__(self, df: pd.DataFrame, tok, max_len: int = MAX_LEN):
        self.rows = df.to_dict("records")
        self.tok = tok
        self.max_len = max_len

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        r = self.rows[i]
        prompt = INSTRUCTION + r["text"] + "\n\nTagged:\n"
        target = tag_text(r["text"], r["spans"])

        p_ids = self.tok(prompt, add_special_tokens=False)["input_ids"]
        t_ids = self.tok(target + self.tok.eos_token, add_special_tokens=False)["input_ids"]
        ids = (p_ids + t_ids)[: self.max_len]
        # -100 on the prompt: the model is graded on what it produces, not on
        # reciting the instruction back.
        labels = ([-100] * len(p_ids) + t_ids)[: self.max_len]
        pad = self.max_len - len(ids)
        attn = [1] * len(ids) + [0] * pad
        ids = ids + [self.tok.pad_token_id] * pad
        labels = labels + [-100] * pad
        return {"input_ids": torch.tensor(ids),
                "attention_mask": torch.tensor(attn),
                "labels": torch.tensor(labels)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=BASE_MODEL)
    ap.add_argument("--train-set", default="train_hard2")
    ap.add_argument("--out", default="generative")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--bf16", action="store_true")
    args = ap.parse_args()

    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              get_linear_schedule_with_warmup)

    torch.manual_seed(args.seed)
    path = SYN / f"injected_{args.train_set}.parquet"
    if not path.exists():
        print(f"missing {path}")
        return 1
    df = pd.read_parquet(path)
    if args.limit:
        df = df.head(args.limit)

    dev = torch.device("cuda" if torch.cuda.is_available()
                       else "mps" if torch.backends.mps.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    # dtype is explicit for the same reason as the encoder: transformers 5.x
    # loads a checkpoint in the dtype it was SAVED in, and a pure-fp16 model
    # destroys itself on the first AdamW step. bf16 is safe where supported;
    # fp32 otherwise. Never fp16.
    dtype = torch.bfloat16 if (args.bf16 and dev.type == "cuda") else torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=dtype).to(dev)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()

    lora = LoraConfig(
        r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"device {dev} | {args.model} | trainable {trainable:,} of {total:,} "
          f"({100*trainable/total:.2f}%)", flush=True)

    dl = DataLoader(TagDataset(df, tok), batch_size=args.batch, shuffle=True)
    steps = math.ceil(len(dl) / GRAD_ACCUM) * args.epochs
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)

    log = ["M3 branch B — generative training log", "=" * 58,
           f"base model      {args.model}",
           f"trainable       {trainable:,} of {total:,} (LoRA r={LORA_R})",
           f"device          {dev}   dtype {dtype}",
           f"training rows   {len(df):,}",
           f"epochs          {args.epochs}  batch {args.batch} x{GRAD_ACCUM} accum",
           f"lr              {LR}   max len {MAX_LEN}",
           f"seed            {args.seed}", ""]

    model.train()
    t_start = time.time()
    for ep in range(args.epochs):
        running = seen = 0
        t0 = time.time()
        opt.zero_grad()
        for step, batch in enumerate(dl):
            batch = {k: v.to(dev) for k, v in batch.items()}
            out = model(**batch)
            (out.loss / GRAD_ACCUM).backward()
            running += out.loss.item()
            seen += 1
            if (step + 1) % GRAD_ACCUM == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step(); sched.step(); opt.zero_grad()
            if seen % 100 == 0:
                done = seen / len(dl)
                eta = (time.time() - t0) * (1 - done) / max(done, 1e-9)
                print(f"  epoch {ep+1} {100*done:5.1f}%  loss {running/seen:.4f}  "
                      f"eta {eta/60:5.1f}m", flush=True)
        line = f"epoch {ep+1}: mean loss {running/max(seen,1):.4f}  ({(time.time()-t0)/60:.1f} min)"
        print("  " + line, flush=True)
        log.append(line)
        d = MODELS / args.out
        d.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(d)
        tok.save_pretrained(d)
        (d / "checkpoint.json").write_text(json.dumps(
            {"epochs_completed": ep + 1, "mean_loss": running / max(seen, 1),
             "base_model": args.model, "adapter": "lora"}, indent=2))

    log += ["", f"total training time  {(time.time()-t_start)/60:.1f} min"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"m3_train_log_{args.out}.txt").write_text("\n".join(log) + "\n")
    print("\n".join(log[-2:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
