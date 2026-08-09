#!/usr/bin/env bash
# Archive the corpus and derived data to S3, with a provenance record.
#
# WHY THIS MATTERS MORE THAN IT LOOKS
# -----------------------------------
# bootstrap.sh downloads the corpus from
#   https://files.consumerfinance.gov/ccdb/complaints.csv.zip
# which is a ROLLING snapshot. The CFPB adds complaints to it continuously and
# publishes no versioned URL. So the corpus is the one artifact in this project
# that is NOT reconstructible:
#
#   trained weights   -> rebuildable, ~$1.20 of GPU time (docs/04a-base-encoder.md)
#   synthetic data    -> regenerates from a fixed seed
#   the CFPB snapshot -> gone the moment the CFPB updates the file
#
# Every published number derives from the 2026-08-06 snapshot. Without an archived
# copy, `make repro` on a later checkout silently reproduces against different
# data and the numbers quietly stop matching -- which is precisely the failure
# constitution principle III exists to prevent.
#
# On the constitution: principle VI says the corpus "does not go in the
# repository". This is not the repository -- it is a private, access-blocked,
# encrypted bucket in the project owner's own AWS account. The data is public
# and CFPB-scrubbed to begin with. Nothing here is committed to git.
#
# Usage: scripts/s3_stage_data.sh [--dry-run]

set -euo pipefail

BUCKET="${AIRLOCK_S3_BUCKET:?set AIRLOCK_S3_BUCKET (see .secrets/README.md)}"
PROFILE="${AWS_PROFILE:-default}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY=""
[[ "${1:-}" == "--dry-run" ]] && DRY="--dryrun"

CORPUS="$ROOT/data/raw/complaints.csv"

echo "== provenance"
PROV="$ROOT/data/raw/PROVENANCE.txt"
if [[ -f "$CORPUS" && ! -f "$PROV" ]]; then
  # sha256 of ~9GB takes about half a minute and is the only thing that lets a
  # later reader prove they have the same snapshot.
  echo "  hashing $(basename "$CORPUS") (~9GB, this takes a moment)..."
  SHA=$(shasum -a 256 "$CORPUS" | awk '{print $1}')
  {
    echo "source_url:      https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
    echo "note:            the source URL is a ROLLING snapshot; it is not versioned"
    echo "                 and cannot be re-fetched as it was on the date below."
    echo "file:            complaints.csv"
    echo "bytes:           $(stat -f%z "$CORPUS")"
    echo "sha256:          $SHA"
    echo "downloaded_utc:  $(date -u -r "$(stat -f%m "$CORPUS")" '+%Y-%m-%dT%H:%M:%SZ')"
    echo "archived_utc:    $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "archived_to:     s3://\$AIRLOCK_S3_BUCKET/data/raw/complaints.csv"
  } > "$PROV"
  echo "  wrote $PROV"
fi
[[ -f "$PROV" ]] && cat "$PROV" | sed 's/^/    /'

# The extracted CSV is the snapshot itself, so it is archived despite its size.
# Interim and synthetic are derived and regenerable, but they are small and
# archiving them saves re-deriving 8.4GB of CSV to get 138MB of parquet back.
for d in raw interim synthetic; do
  [[ -d "$ROOT/data/$d" ]] || continue
  echo "== data/$d -> s3://$BUCKET/data/$d/"
  aws s3 sync "$ROOT/data/$d" "s3://$BUCKET/data/$d/" \
      --profile "$PROFILE" --only-show-errors $DRY
done

echo
echo "== verifying"
aws s3 ls "s3://$BUCKET/data/" --recursive --human-readable --summarize \
    --profile "$PROFILE" | tail -20
