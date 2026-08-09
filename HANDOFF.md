# Handoff — 2026-08-09 (evening)

Supersedes the morning handoff of the same date. **Read
[the constitution](.specify/memory/constitution.md), then
[docs/09-lessons.md](docs/09-lessons.md), then `DECISIONS/`.**

Two claims in the previous version of this file did not survive checking. They
are corrected in §5 rather than deleted, because that is the point.

---

## 1. Nothing is billing

**Instance 47213776 was destroyed at 22:15 UTC.** Final cost **$4.62** over 24.4
hours. No rented hardware is running.

```bash
.venv-tools/bin/vastai show instances    # expect an empty list
```

---

## 2. Where everything lives

All ten trained models are in S3, **sha256-verified round-trip** against the box
before it was destroyed.

```bash
export AIRLOCK_S3_BUCKET=<the bucket>          # see .secrets/env
aws s3 ls s3://$AIRLOCK_S3_BUCKET/ --recursive --summarize --human-readable
```

| prefix | contents |
|---|---|
| `m3/models/` | micro-08, base2 ×3, large ×3, generative (writer LoRA) |
| `data/raw/` | `complaints.csv` + `PROVENANCE.txt` (sha256-stamped) |
| `data/interim/`, `data/synthetic/` | derived parquet |
| `results/` | every results file and run log |

Local: `micro-s20260806/07` were already here; `base2-s20260806` and
`micro-s20260808` were pulled back from S3 for M5.

**The corpus is the only artifact that cannot be rebuilt.** `bootstrap.sh` fetches
a rolling URL with no versioning, so the 2026-08-06 snapshot is gone the moment
the CFPB updates it. Its sha256 is in `results/corpus_provenance.txt`.

The nine ablation models (data-scaling and epoch runs, 7.8 GB) were **not**
transferred — regenerable in ~50 GPU-minutes via `scripts/m6_data_scaling.sh` and
`scripts/m6_epoch_ablation.sh`, versus 6+ hours to move at the box's real uplink.

---

## 3. The headline changed

**The M3 result is not a finding about model size.** It is a finding about our
training recipe. One learning rate for three scales, a fixed 3 epochs, no
validation split and no early stopping — so each arm was scored at a different
point on its own overfitting curve.

Retrained for one epoch, changing nothing else:

| arm | 1 epoch | 3 epochs |
|---|---:|---:|
| micro 70.7M | 83.8 | **85.5** |
| base2 184M | 82.1 | 77.4 |
| large 434M | **84.7** | 78.0 |

The ranking inverts. See
[decision 017](DECISIONS/017-the-training-recipe-invalidates-the-size-comparison.md);
[decision 015](DECISIONS/015-why-micro-beats-large.md) is superseded in part and
says so at the top.

**Do not publish a size ranking.** The effect is smaller than the seed spread
(±0.5 to ±2.9 F1). Resolving it properly needs ~30 seeds per arm — about 40 GPU
hours for `large` alone. The defensible claim is *indistinguishable on accuracy,
decisively different on cost* (192 vs 63 narratives/sec is not a noise-level
difference).

---

## 4. Results now committed

**M5 — the leakage/utility trade** (`results/m5_utility.txt`):

| method | re-ident | utility | utility lost |
|---|---:|---:|---:|
| raw | 36.9% | 48.0% | 0.0 |
| presidio | 1.2% | 44.4% | 3.6 |
| **airlock:micro** | **0.2%** | 47.3% | **0.7** |
| airlock:base2 | 0.2% | 46.7% | 1.3 |
| spacy | 0.0% | 38.9% | 9.1 |

Airlock is the best trade: near-zero leakage for a fraction of Presidio's utility
cost, while spaCy buys 0% leakage by destroying the text — the over-redaction
failure M4 predicted.

**Writer arm** (`results/m3_arms.txt`): F1 67.4%, precision 99.5% (highest of any
arm), recall 50.9% — because **26.3% of outputs were too mangled to align** and
score as redacting nothing. Truncation was ruled out as the cause.

**Writer cost** (`results/m3_writer_cost.txt`): 3,176 → 1,200 ms/narrative under
fair tuning. The gap to micro is **267×, not 690×**.

---

## 5. Corrections to the previous handoff

1. **"`relief` scored 0% even on raw text"** — it scored **75.0%**, the highest of
   the three questions. Nothing in the repo supported 0%. The instruction to drop
   it was conditional on that figure, so it was not dropped.
2. **"drift measurement is built and unit-tested"** — there were **no tests**.
   There are now: `scripts/test_m3_predict_generative.py`, 7 passing, including
   an ordering test, because length-bucketing would otherwise silently map every
   span onto the wrong narrative.

---

## 6. Still owed

- **`make repro` — blocked on a decision, not on work.** It stops at M4 and still
  points at the old single-model path. Fixing the wiring is easy; the blocker is
  that [decision 011](DECISIONS/011-training-moves-to-rented-gpu.md) requires
  repro to *publish* weights so it need not retrain — and a private bucket is
  backup, not publication. **Fork: public bucket, Hugging Face Hub, or accept
  that repro retrains.** Human's call.
- **Two known-false numbers still in `m3_arms.txt`**, both flagged in the README:
  per-category recall prints `0.0%` for methods that were never run, and the
  "INFERENCE COST ON THE M1" block prints `0 MB` / `7 MB` from a run on a GPU box.
- `docs/01-why.md`, `02-data.md`, `06-utility.md` are stubs. `06-utility.md`
  now has real numbers to write up.
- `make prune-superseded` — reclaims 4.2 GB of superseded local weights.
- The span-emitting writer ([decision 016](DECISIONS/016-span-emitting-writer-proposed.md))
  is proposed and costed, not built.

---

## 7. Failure modes, cumulative

The four from the morning handoff still stand (`pkill -f` matching itself;
unverified commands hidden behind pipes; scripts not synced before invocation;
an eval silently falling back to CPU). Today added:

5. **A comparison across model scales is only a comparison if each scale gets its
   own stopping point.** A shared schedule turns a capacity experiment into a
   schedule experiment, and the output still looks clean.
6. **Verify a correct answer is reachable before believing a low score.** Three
   separate answer keys in M5 were unachievable by construction.
7. **`pkill` kills the parent, not its children.** Orphaned workers duplicated
   uploads and corrupted a log by writing to a truncated file.
8. **A timeout shorter than the work is a livelock, not a failure.** Parts were
   killed just short of completing and restarted from zero, forever, while the
   network graph looked healthy.

Full write-up, in plain language: [docs/09-lessons.md](docs/09-lessons.md).
