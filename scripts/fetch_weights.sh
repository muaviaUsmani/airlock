#!/usr/bin/env bash
# Fetch published models and data from the public bucket. No AWS account needed.
#
# WHY THIS EXISTS
# ---------------
# Constitution principle III requires every published number to regenerate from
# a clean checkout, and decision 011 commits `make repro` to doing that WITHOUT
# retraining -- "a repro that silently requires a rented A100 is not a repro".
# That needs the trained weights to be fetchable by someone who is not us.
#
# Everything here is public and anonymous: `--no-sign-request` sends no
# credentials, so this works on a machine that has never seen an AWS key.
#
#   scripts/fetch_weights.sh models     # the 10 trained arms (7.3 GiB)
#   scripts/fetch_weights.sh data       # synthetic + interim parquet (223 MiB)
#   scripts/fetch_weights.sh corpus     # the pinned CFPB snapshot (8.4 GiB)
#   scripts/fetch_weights.sh repro      # what `make repro` needs: models + data
#   scripts/fetch_weights.sh all        # everything (15.9 GiB)
#
# The corpus is deliberately separate. It is the largest object here and the
# only one that cannot be rebuilt -- its source URL is a rolling snapshot with
# no versioning, so this copy is the only way to get the exact bytes the
# published numbers were computed from. Most people do not need it.
set -euo pipefail

BUCKET="${AIRLOCK_PUBLIC_BUCKET:-airlock-redaction}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S3="aws s3 --no-sign-request"

command -v aws >/dev/null || { echo "aws cli required: https://aws.amazon.com/cli/" >&2; exit 1; }

get() {  # get <s3-subpath> <local-dir>
  echo "== s3://$BUCKET/$1 -> $2"
  mkdir -p "$2"
  $S3 sync "s3://$BUCKET/$1" "$2" --no-progress
}

case "${1:-repro}" in
  models) get m3/models        "$ROOT/models" ;;
  data)   get data/synthetic   "$ROOT/data/synthetic"
          get data/interim     "$ROOT/data/interim" ;;
  corpus) get data/raw         "$ROOT/data/raw" ;;
  repro)  get m3/models        "$ROOT/models"
          get data/synthetic   "$ROOT/data/synthetic"
          get data/interim     "$ROOT/data/interim" ;;
  all)    get m3/models        "$ROOT/models"
          get data             "$ROOT/data"
          get results          "$ROOT/results" ;;
  *) echo "usage: $0 {models|data|corpus|repro|all}" >&2; exit 2 ;;
esac

# The corpus is the one artifact that cannot be regenerated, so its integrity is
# checked rather than assumed whenever it is present.
if [[ -f "$ROOT/data/raw/complaints.csv" && -f "$ROOT/data/raw/PROVENANCE.txt" ]]; then
  want=$(awk '/^sha256:/{print $2}' "$ROOT/data/raw/PROVENANCE.txt")
  echo "== verifying corpus against PROVENANCE (this reads 8.4 GiB)"
  got=$(shasum -a 256 "$ROOT/data/raw/complaints.csv" | awk '{print $1}')
  if [[ "$want" == "$got" ]]; then
    echo "   ok  $got"
  else
    echo "   !! CORPUS MISMATCH: want $want got $got" >&2
    exit 1
  fi
fi

echo "done."
