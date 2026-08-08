#!/usr/bin/env bash
# Every training run for one rented session.
#
# Setup time is billed and dominates a 15-minute job, so renting once and running
# everything beats renting per-arm (decision 011).
#
# Three seeds each, because every number in this project before the first sweep
# was n=1 — and that sweep showed the authored arm's recall varying by ±17
# points, which a single run would have reported as a finding.
#
# ARMS
#   base    deberta-v3-base   184M  the current result, for continuity
#   micro   deberta-v3-xsmall  22M  ~70MB — the laptop-demo claim (decision 012)
#   large   deberta-v3-large  434M  what staying small actually costs
#
# All three train on the SAME hardened data, so any difference is capacity, not
# data. Inference latency for each is measured afterwards on the M1, because a
# rented GPU cannot speak to the demo claim.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-/venv/main/bin/python}
$PY -c "import torch; assert torch.cuda.is_available(); print('gpu:', torch.cuda.get_device_name(0))"

run () {  # run <model> <tag> <batch>
  for SEED in 20260806 20260807 20260808; do
    echo "=== $2 seed $SEED ==="
    $PY -u scripts/m3_train_encoder.py \
        --model "$1" --train-set train_hard2 --out "encoder-$2-s${SEED}" \
        --seed "$SEED" --batch "$3" --bf16
  done
}

run microsoft/deberta-v3-xsmall micro 16
run microsoft/deberta-v3-base   base2 8      # waypoint, not a deliverable — see docs/04a
run microsoft/deberta-v3-large  large 4

# Branch B: a different ARCHITECTURE, not a bigger one. Reopened by decision 012
# after decision 009 closed it on an inference cost that no longer applies.
# ~0.6B against large's 434M, so this is close to a size-matched architecture
# comparison rather than a capacity one.
for SEED in 20260806 20260807 20260808; do
  echo "=== generative seed $SEED ==="
  $PY -u scripts/m3_train_generative.py \
      --train-set train_hard2 --out "generative-s${SEED}" --seed "$SEED" --bf16
done

echo
echo "Done. Bring the weights back, then evaluate ON THE LAPTOP:"
echo "  rsync -az -e 'ssh -i ~/.ssh/airlock_vast -p PORT' root@HOST:/workspace/airlock/models/ models/"
