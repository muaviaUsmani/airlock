#!/usr/bin/env bash
# M6 — does 15,000 examples starve the larger arms?
#
# HANDOFF §4 offered two explanations for micro beating large, and
# DECISIONS/015 settled one of them: the larger arms memorise carrier phrasing
# and transfer worse. That rules memorisation IN. It does not rule starvation
# OUT -- 15,000 examples may simply underdetermine 434M parameters, in which
# case large is not overfitting so much as never finishing learning.
#
# Those two stories make DIFFERENT predictions about the shape of an
# accuracy-versus-training-size curve:
#
#   starved   -> large is still climbing steeply between 5k and 15k. More data
#                would keep helping, and the comparison at 15k is premature.
#   saturated -> large has flattened by 15k, the same as micro. More data would
#                not change the ranking, and the M3 headline stands as measured.
#
# Only 2k and 5k are trained here. The 15k point already exists: the arms
# trained by train_all_seeds.sh. Seed is fixed at 20260806 across every point so
# the curve varies in ONE thing -- training rows.
#
# Batch sizes match train_all_seeds.sh exactly, because changing the batch would
# change the effective learning rate and put a second variable in the curve.
#
# ~30 min on a 3090. Writes models/encoder-<arm>-n<size>-s20260806/
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-/venv/main/bin/python}
SEED=20260806
SIZES=${SIZES:-"2000 5000"}

$PY -c "import torch; assert torch.cuda.is_available(); print('gpu:', torch.cuda.get_device_name(0))"

run () {  # run <hf-model> <arm> <batch>
  for N in $SIZES; do
    OUT="encoder-$2-n${N}-s${SEED}"
    if [ -f "models/$OUT/model.safetensors" ]; then
      echo "=== $OUT already trained, skipping"
      continue
    fi
    echo "=== $2  n=$N  seed $SEED"
    $PY -u scripts/m3_train_encoder.py \
        --model "$1" --train-set train_hard2 --out "$OUT" \
        --seed "$SEED" --batch "$3" --limit "$N" --bf16
  done
}

run microsoft/deberta-v3-xsmall micro 16
run microsoft/deberta-v3-base   base2 8
run microsoft/deberta-v3-large  large 4

echo
echo "training done. Evaluate with: scripts/m6_data_scaling.py"
