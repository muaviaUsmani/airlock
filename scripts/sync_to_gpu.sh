#!/usr/bin/env bash
# Ship the minimum needed to train on a rented GPU box, and nothing else.
#
# WHAT LEAVES THIS MACHINE (decision 011):
#   scripts/                       ~200 KB  code
#   data/synthetic/injected_*.parquet       the training + eval sets
#   requirements.txt
#
# WHAT DOES NOT:
#   data/raw/ and data/interim/    the 8.4 GB CFPB corpus. Never needed on the
#                                  GPU box — all data generation is CPU work and
#                                  stays local.
#
# Nothing confidential is uploaded. The training data is public CFPB text with
# synthetic personal information we generated ourselves (decision 003), which is
# what makes renting compute compatible with this project's privacy premise.
#
#   usage: ./scripts/sync_to_gpu.sh <ssh-host> <ssh-port>
set -euo pipefail

HOST="${1:?ssh host, e.g. ssh5.vast.ai}"
PORT="${2:?ssh port, e.g. 41234}"
KEY="${SSH_KEY:-$HOME/.ssh/airlock_vast}"     # dedicated key, created for this
REMOTE="root@${HOST}"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"
DEST="/workspace/airlock"

echo "==> checking connectivity"
$SSH -p "$PORT" -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE" \
    'echo connected; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader'

echo "==> creating $DEST"
$SSH -p "$PORT" "$REMOTE" "mkdir -p $DEST/data/synthetic $DEST/results $DEST/models"

echo "==> uploading (size shown below, should be ~150-250 MB)"
du -ch scripts requirements.txt data/synthetic/injected_*.parquet | tail -1
rsync -az -e "$SSH -p $PORT" \
      scripts requirements.txt "$REMOTE:$DEST/"
rsync -az -e "$SSH -p $PORT" \
      data/synthetic/injected_*.parquet "$REMOTE:$DEST/data/synthetic/"

echo "==> installing deps (torch is usually preinstalled on vast pytorch images)"
$SSH -p "$PORT" "$REMOTE" "cd $DEST && python -m pip install -q --upgrade \
    'transformers>=4.44' 'pandas>=2.2' pyarrow accelerate sentencepiece protobuf"

echo
echo "Ready. Train with:"
echo "  $SSH -p $PORT $REMOTE 'cd $DEST && bash scripts/train_all_seeds.sh'"
