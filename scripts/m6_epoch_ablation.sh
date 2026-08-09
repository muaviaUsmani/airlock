#!/usr/bin/env bash
# M6 — is the inverted size ranking caused by our training recipe?
#
# m3_train_encoder.py trains every arm for a FIXED 3 epochs, with a FIXED
# lr=3e-5, and keeps the last epoch. There is no validation split, no early
# stopping and no best-checkpoint selection. The training losses at 15k rows
# show what that costs:
#
#     arm     epoch1   epoch2   epoch3
#     micro   0.3684   0.0095   0.0053
#     base2   0.1240   0.0012   0.0005
#     large   0.0711   0.0006   0.0003
#
# large has memorised the training set by epoch 2 and then trains a third epoch
# anyway; micro still has signal left when training stops. So the arms are not
# compared at equivalent points -- each is evaluated wherever a fixed schedule
# happened to leave it, and the more capacity a model has the further past its
# own optimum that is.
#
# This trains all three for ONE epoch and nothing else changes. If the ranking
# moves -- large gaining while micro is flat or worse -- then "small beats
# large" is a statement about the recipe, not about capacity, and the M3
# headline needs rewording before publication.
#
# Deliberately NOT also changing the learning rate. lr=3e-5 is likely too hot
# for deberta-v3-large, but changing two things at once would leave neither
# testable. LR is a separate experiment (and is currently a module constant,
# not a CLI argument, which is its own problem).
#
# ~21 min on a 3090.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-/venv/main/bin/python}
SEED=20260806

# Wait for any evaluation already using the GPU, so the two do not contend.
while pgrep -f "[m]3_writer_cost" >/dev/null; do sleep 20; done

run () {  # run <hf-model> <arm> <batch>
  OUT="encoder-$2-e1-s${SEED}"
  if [ -f "models/$OUT/model.safetensors" ]; then
    echo "=== $OUT exists, skipping"; return
  fi
  echo "=== $2  1 epoch  seed $SEED"
  $PY -u scripts/m3_train_encoder.py \
      --model "$1" --train-set train_hard2 --out "$OUT" \
      --seed "$SEED" --batch "$3" --epochs 1 --bf16
}

run microsoft/deberta-v3-xsmall micro 16
run microsoft/deberta-v3-base   base2 8
run microsoft/deberta-v3-large  large 4

echo "training done"
