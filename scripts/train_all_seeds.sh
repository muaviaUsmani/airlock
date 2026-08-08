#!/usr/bin/env bash
# Every training run we need, in one rented session.
#
# Setup time is billed and dominates a 15-minute job, so renting once and
# running everything beats eleven separate rentals (decision 011).
#
# Three seeds of each arm, because every number in this project so far is n=1 —
# the weakest methodological point in the repository, and purely a compute
# artefact.
set -euo pipefail
cd "$(dirname "$0")/.."

python -c "import torch; assert torch.cuda.is_available(); \
print('gpu:', torch.cuda.get_device_name(0))"

for SEED in 20260806 20260807 20260808; do
  # CONTROL: the original authored-carrier data, so the comparison has a
  # baseline trained on this hardware rather than across two platforms.
  python -u scripts/m3_train_encoder.py --train-set train \
      --out "encoder-authored-s${SEED}" --seed "$SEED" --bf16

  # TREATMENT: hardened injector — real carriers, split value pools, hard
  # negatives (decision 010).
  python -u scripts/m3_train_encoder.py --train-set train_hard \
      --out "encoder-hard-s${SEED}" --seed "$SEED" --bf16
done

echo
echo "Six runs done. Bring the weights back:"
echo "  rsync -az -e 'ssh -p PORT' root@HOST:/workspace/airlock/models/ models/"
echo
echo "Then evaluate ON THE LAPTOP — inference latency is the claim, and this"
echo "box cannot measure it (decision 011)."
