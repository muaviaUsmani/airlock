#!/usr/bin/env bash
# Provision-agnostic training entrypoint for a rented GPU box (decision 011).
#
# Nothing confidential is uploaded: the training data is public CFPB text with
# synthetic personal information we generated ourselves (decision 003).
#
# The human provisions and pays for the instance. This script does not.
#
#   usage:  ./scripts/run_on_gpu.sh <train-set> <out-name> [seed]
#   e.g.    ./scripts/run_on_gpu.sh train_rc airlock-encoder-rc 20260806
set -euo pipefail

TRAIN_SET="${1:-train}"
OUT="${2:-airlock-encoder}"
SEED="${3:-20260806}"

python -c "import torch; assert torch.cuda.is_available(), 'no CUDA visible'; \
print('gpu:', torch.cuda.get_device_name(0))"

python -u scripts/m3_train_encoder.py \
  --train-set "$TRAIN_SET" \
  --out "$OUT" \
  --seed "$SEED" \
  --bf16

echo
echo "Done. Copy models/$OUT back to the laptop, then run there:"
echo "  .venv/bin/python scripts/m3_evaluate.py --model-dir models/$OUT"
echo
echo "Inference latency MUST be measured on the M1 — that is the claim being"
echo "made, and it is the one thing this box cannot tell you (decision 011)."
