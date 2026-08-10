#!/usr/bin/env bash
# Run the whole milestone chain at small sample sizes, to prove the wiring.
#
# WHY THIS IS SEPARATE FROM `make repro`
# --------------------------------------
# A full repro on an M1 is about seven hours, most of it m6_overfit_gap scoring
# four evaluation sets against nine arms. That is the right cost for
# regenerating published numbers and the wrong cost for answering "does the
# pipeline still run at all", which is the question that actually breaks.
#
# WHY IT RESTORES results/
# ------------------------
# Every script writes to results/ unconditionally. Running the chain at n=120
# would therefore overwrite committed, published numbers with small-sample ones
# that look exactly like them -- the precise failure this project keeps finding
# in itself. So results/ is copied aside first and put back afterwards, on
# success, on failure, and on Ctrl-C.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
RESULTS="$ROOT/results"
N="${SMOKE_N:-120}"

BACKUP="$(mktemp -d)"
restore() {
  if [[ -d "$BACKUP/results" ]]; then
    rm -rf "$RESULTS"
    mv "$BACKUP/results" "$RESULTS"
    echo "results/ restored from backup"
  fi
  rm -rf "$BACKUP"
}
trap restore EXIT INT TERM

mkdir -p "$RESULTS"
cp -a "$RESULTS" "$BACKUP/results"
echo "results/ backed up ($(find "$BACKUP/results" -type f | wc -l | tr -d ' ') files); running chain at n=$N"
echo

rc=0
run() {
  echo "== $*"
  if ! "$@"; then
    echo "!! FAILED: $*" >&2
    rc=1
    return 1
  fi
}

run "$PY" scripts/m3_compare_arms.py --n "$N" --arms micro,base2,large || true
run "$PY" scripts/m4_attack.py --set natural_v2 --n "$N"               || true
run "$PY" scripts/m6_overfit_gap.py --n "$N" --arms micro,base2,large  || true

# m6_ablate_dbsize is deliberately NOT here. It REGENERATES the canonical
# synthetic database at 10k/40k/160k customers and restores it in a finally
# block -- safe when it completes, but a SIGKILL mid-sweep would leave the repo
# holding a database of the wrong size that every later M4 run would silently
# use. Its smallest size is also floored by the 4,000 customers the injected set
# references, so there is no cheap version of it. It runs in `make m6`.

echo
if (( rc == 0 )); then
  echo "CHAIN OK — every milestone ran and fed the next."
  echo "These were small-sample runs; results/ has been restored to the published numbers."
else
  echo "CHAIN BROKEN — see failures above." >&2
fi
exit $rc
