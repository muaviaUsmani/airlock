# Setup and running

Everything here works with no AWS account, no API key and no GPU — except M5,
which needs one API key, and two ablations that need CUDA. Both are called out
where they apply.

---

## 1. First run

```bash
git clone <this repo> && cd airlock
./scripts/bootstrap.sh
```

That builds a virtual environment at `.venv/`, installs dependencies, downloads
the CFPB corpus (~1.3 GB compressed, ~8.4 GB unpacked) and records which nightly
build you got.

The corpus is **never committed**. It is public data republished every night, so
what belongs in git is the download step plus a record of which night the numbers
came from.

> **The download is not reproducible, and that is worth knowing up front.**
> `https://files.consumerfinance.gov/ccdb/complaints.csv.zip` is a rolling
> pointer with no versioning — you cannot ask for the file as it was on a given
> date. Running `bootstrap.sh` today gets you *today's* corpus, and your numbers
> will differ slightly from the published ones. To reproduce them exactly, fetch
> the pinned snapshot instead (step 2).

## 2. Get the published models and the pinned corpus

```bash
make weights                      # the 10 trained arms, 7.3 GiB
scripts/fetch_weights.sh corpus   # the exact corpus the numbers came from, 8.4 GiB
```

Anonymous — these send no credentials and need no AWS account:

```bash
aws s3 sync s3://airlock-redaction/m3/models models --no-sign-request
curl -O https://airlock-redaction.s3.amazonaws.com/results/m5_utility.txt
```

| what | size | why you might skip it |
|---|---:|---|
| `m3/models/` | 7.3 GiB | needed for everything past M2 |
| `data/synthetic/` | 85 MiB | regenerable with `make m2` |
| `data/interim/` | 138 MiB | regenerable with `make m0` |
| `data/raw/` | 8.4 GiB | only needed to reproduce the published numbers *exactly* |
| `results/` | 305 KiB | the numbers themselves, for comparison |

`fetch_weights.sh` verifies the corpus against the sha256 in its `PROVENANCE.txt`
whenever it is present. It is the one artifact here that cannot be rebuilt, so it
is checked rather than trusted.

## 3. Running it on a Mac

```bash
make repro-smoke     # ~3 min — proves the whole chain runs
make repro           # ~7 hours — regenerates every published number
```

**Start with `repro-smoke`.** It runs the identical chain at n=60, then restores
`results/` to the committed numbers, so a wiring check cannot quietly replace
published figures with small-sample ones that look the same.

`make repro` prints its cost before spending it. On an M1:

| stage | approximate |
|---|---|
| m0 corpus characterisation | 20 min |
| m1 baselines | 30 min |
| m2 injection + adversary | 10 min |
| m3 four-arm comparison | 60 min |
| m4 the attack | 20 min |
| m5 utility | 20 min, **~$2 of API credit** |
| m6 db-size ablation | 1–2 h |
| m6 overfit-gap | **~5.7 h** |

The last row dominates: it scores four evaluation sets against nine arms. If you
only want the headline, `make m3 m4` is about 80 minutes.

**Apple Silicon notes.** Torch uses the `mps` backend automatically. Inference is
roughly 16× slower than a rented 3090 — micro measures ~72 ms/narrative on an M1
against ~4.5 ms on the GPU. Nothing needs configuring; it is just slow.

## 4. Running it on a GPU

Two things are deliberately outside `make repro`, because the writer generates
~365 tokens per narrative and that is hours on a laptop:

```bash
make gpu-arms        # writer cost + data-scaling + epoch ablations (needs CUDA)
```

To retrain every arm instead of fetching them — same seeds, same results:

```bash
make train           # ~1.5 h on a 3090
```

`make repro` does **not** retrain, on purpose:
[decision 011](../DECISIONS/011-training-moves-to-rented-gpu.md) requires it not
to — *a repro that silently requires a rented A100 is not a repro*.

**On rented hardware**, two things cost more than expected and are worth knowing
before you start:

- **Check the uplink before trusting it.** The instance used here advertised
  192 Mbit/s and delivered ~0.4 MB/s per stream. Moving 7.8 GB off it took longer
  than the training did.
- **Parallelism is the only lever that worked.** Six concurrent streams got ~5×
  the throughput of one. `scripts/s3_stage_weights.py` does this with presigned
  multipart URLs, so no AWS credential ever lands on rented hardware.

## 5. The one credential

M5 — and only M5 — calls a frontier model. It reads `ANTHROPIC_API_KEY` from the
environment:

```bash
cp .secrets/env.example .secrets/env    # then fill it in
set -a; . ./.secrets/env; set +a
make m5
```

`.secrets/` is gitignored. Nothing else in the project needs a key, and
`make repro` fails fast with a readable message rather than part-way through if
it is missing.

## 6. Docker

```bash
docker compose run --rm airlock make repro
```

Same thing, no Python version to match.

## 7. Useful targets

```bash
make help                # everything, with one-line descriptions
make m3                  # just the four-arm comparison
make weights             # fetch models
make prune               # delete regenerable artifacts
make prune-superseded    # also delete arms whose numbers were superseded (4.2 GB)
```

## 8. If something breaks

- **`make m3` says weights are missing** — run `make weights` first.
- **Numbers differ slightly from the published ones** — you almost certainly have
  a newer corpus. See the warning in step 1; fetch the pinned snapshot.
- **A stage seems hung** — several write results only at the end and show no
  progress meanwhile. `m6_overfit_gap` in particular runs for hours silently.
  Check CPU with `ps -o etime=,time= -p <pid>` rather than assuming.
- **A run was interrupted part-way** — `results/` is under version control;
  `git checkout HEAD -- results/` restores the published numbers. This is not
  hypothetical, it is how they were recovered during development.
