#!/usr/bin/env bash
# Runs ON the rented GPU box. Reads a manifest of presigned S3 URLs and uploads
# the corresponding byte ranges in parallel.
#
# It holds no AWS credentials -- only time-limited URLs signed on the laptop.
#
# Six workers, because that is where the measured aggregate throughput topped
# out (0.42 MB/s on one stream, ~2.0 MB/s across six).
#
# Usage: s3_upload_parts.sh MANIFEST.jsonl [PARALLEL]

set -uo pipefail

MANIFEST="${1:?manifest required}"
PARALLEL="${2:-6}"
TMPDIR_PARTS="${TMPDIR_PARTS:-/tmp/s3parts}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-6}"
# Must comfortably exceed part_size / per-stream throughput, or parts are killed
# just short of finishing and restarted from zero -- a livelock that looks like
# steady network traffic with nothing ever completing. Observed at 24 streams:
# ~87 KB/s per stream, so a 64MiB part needs ~770s and a 900s cap killed them.
MAX_TIME="${MAX_TIME:-5400}"

mkdir -p "$TMPDIR_PARTS"

upload_one() {
  # Fields are tab-separated: id, src, offset, length, url
  IFS=$'\t' read -r id src offset length url <<< "$1"

  local part="$TMPDIR_PARTS/$id"
  local attempt=0 code

  # Slice the byte range out of the source file. count_bytes makes the final
  # short part exact rather than rounded up to a whole MiB.
  if ! dd if="$src" bs=1M skip=$(( offset / 1048576 )) \
        iflag=count_bytes count="$length" of="$part" 2>/dev/null; then
    echo "SLICE-FAIL $id" >&2
    return 1
  fi

  local got
  got=$(stat -c %s "$part")
  if [[ "$got" != "$length" ]]; then
    echo "SLICE-SHORT $id ($got != $length)" >&2
    rm -f "$part"
    return 1
  fi

  while (( attempt < MAX_ATTEMPTS )); do
    attempt=$(( attempt + 1 ))
    # --fail so a 4xx/5xx is an error rather than a silently stored error page.
    code=$(curl -sS --fail-with-body -X PUT -T "$part" "$url" \
             --max-time "$MAX_TIME" --connect-timeout 30 \
             -o /dev/null -w '%{http_code}' 2>/dev/null)
    if [[ "$code" == "200" ]]; then
      rm -f "$part"
      echo "OK $id"
      return 0
    fi
    sleep $(( attempt * 3 ))
  done

  rm -f "$part"
  echo "FAIL $id (last http $code)" >&2
  return 1
}
export -f upload_one
export TMPDIR_PARTS MAX_ATTEMPTS MAX_TIME

# The manifest is tab-separated so xargs/bash can split it without a JSON parser.
total=$(wc -l < "$MANIFEST")
echo "uploading $total jobs, $PARALLEL at a time"

xargs -d '\n' -P "$PARALLEL" -I{} bash -c 'upload_one "$@"' _ {} < "$MANIFEST"
rc=$?

rmdir "$TMPDIR_PARTS" 2>/dev/null
echo "worker exit $rc"
exit $rc
