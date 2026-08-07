#!/usr/bin/env bash
#
# Sets up everything Airlock needs to run, from a fresh clone, on a Mac with
# nothing installed but Python.
#
# It does three things, and each one is safe to run again:
#   1. builds a virtual environment at .venv/ and installs dependencies into it
#   2. downloads the CFPB consumer complaint corpus (~1.3GB compressed)
#   3. unpacks it (~8.4GB on disk) and records a checksum of what it got
#
# The corpus is never committed to this repository — it is public data that is
# re-published nightly, so the honest thing to store is the download step and a
# record of which nightly build the numbers came from. That record lands in
# data/raw/MANIFEST.txt.
#
# Usage:  ./scripts/bootstrap.sh
#         ./scripts/bootstrap.sh --skip-data     (environment only)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CORPUS_URL="https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
RAW_DIR="data/raw"
ZIP_PATH="$RAW_DIR/complaints.csv.zip"
CSV_PATH="$RAW_DIR/complaints.csv"
MANIFEST="$RAW_DIR/MANIFEST.txt"

SKIP_DATA=0
[[ "${1:-}" == "--skip-data" ]] && SKIP_DATA=1

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die() { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Python environment
# ---------------------------------------------------------------------------
say "Python environment"

# Airlock needs 3.12+. Find an interpreter that qualifies rather than trusting
# whatever "python3" happens to point at — a pyenv shim may be much older.
find_python() {
    for candidate in python3.13 python3.12 python3 "$HOME/.pyenv/versions/3.12.9/bin/python"; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
                echo "$candidate"; return 0
            fi
        fi
    done
    return 1
}

if [[ ! -x .venv/bin/python ]]; then
    PY="$(find_python)" || die "no Python 3.12+ found. Install one (brew install python@3.12) and re-run."
    echo "using $($PY --version) at $(command -v "$PY")"
    "$PY" -m venv .venv
else
    echo ".venv already exists, reusing it"
fi

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .
echo "installed: $(.venv/bin/python -c 'import pandas; print("pandas", pandas.__version__)')"

if [[ $SKIP_DATA -eq 1 ]]; then
    say "Done (skipped data)"
    exit 0
fi

# ---------------------------------------------------------------------------
# 2. Corpus download
# ---------------------------------------------------------------------------
say "CFPB corpus"
mkdir -p "$RAW_DIR"

if [[ -f "$CSV_PATH" ]]; then
    echo "$CSV_PATH already present ($(du -h "$CSV_PATH" | cut -f1)), skipping download"
else
    # --continue-at resumes a partial download instead of restarting 1.3GB.
    echo "downloading $CORPUS_URL (~1.3GB, this takes a few minutes)"
    curl --fail --location --continue-at - --progress-bar -o "$ZIP_PATH" "$CORPUS_URL" \
        || die "download failed. Check the URL is still live: $CORPUS_URL"

    say "Unpacking"
    unzip -o -q "$ZIP_PATH" -d "$RAW_DIR" || die "unzip failed — the download may be truncated; delete $ZIP_PATH and re-run"
fi

[[ -f "$CSV_PATH" ]] || die "expected $CSV_PATH after unpacking, but it is not there"

# ---------------------------------------------------------------------------
# 3. Record what we got
# ---------------------------------------------------------------------------
# The CFPB refreshes this file nightly, so "the corpus" is not one fixed thing.
# Anyone comparing their numbers to ours needs to know which night they have.
say "Recording provenance"
{
    echo "source_url:     $CORPUS_URL"
    echo "downloaded_utc: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "csv_bytes:      $(wc -c < "$CSV_PATH" | tr -d ' ')"
    echo "csv_sha256:     $(shasum -a 256 "$CSV_PATH" | cut -d' ' -f1)"
} > "$MANIFEST"
cat "$MANIFEST"

say "Ready. Next: make m0"
