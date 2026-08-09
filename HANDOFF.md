# Handoff — 2026-08-09

Written because the previous session ran out of context mid-run. **Read
[the constitution](.specify/memory/constitution.md) and `DECISIONS/` before touching anything.**

---

## 1. URGENT — there is a rented GPU billing right now

**Instance `47213776`, RTX 3090, $0.19/hr.** It has already cost ~$3 because a teardown guard
refused to destroy it and then waited indefinitely with nobody watching.

```bash
.venv-tools/bin/vastai show instances          # is it still up?
```

**Do not destroy it until the weights are down** (section 2), then destroy immediately:

```bash
yes | .venv-tools/bin/vastai destroy instance 47213776
```

If the download cannot be completed, **destroy it anyway**. Every model is reconstructible from
`docs/04a-base-encoder.md` and `scripts/train_all_seeds.sh`; six GPU-hours is ~$1.20 at this
rate, which is cheaper than another day of idle billing.

---

## 2. What is still on the box and not on disk

SSH: `ssh -i ~/.ssh/airlock_vast -p 12624 root@137.175.76.24`, path `/workspace/airlock`.

| model | local? |
|---|---|
| `encoder-micro-s20260806/07` | ✅ |
| `encoder-micro-s20260808` | ❌ |
| `encoder-base2-s2026080{6,7,8}` | ❌ |
| `encoder-large-s2026080{6,7,8}` | ❌ |
| `generative-s20260806` | ❌ |

**Downloads keep failing on files over ~300MB** — "broken pipe" / "unexpected end of file".
`rsync --partial --partial-dir` with retries gets micro through but not the 710MB/1.7GB files.
Untried: `ssh root@host 'cat file' > local`, or `tar | ssh`, both single-stream.

Also pull `/workspace/airlock/results/` and `/workspace/airlock/eval.log`.

---

## 3. What was running when the session ended

`scripts/m3_compare_arms.py` on the GPU. **All nine encoder arms finished**; the writer arm was
still generating (~20–40 min). If `results/m3_arms.txt` exists on the box, it completed.

```bash
ssh ... 'tail -40 /workspace/airlock/eval.log; ls /workspace/airlock/results/m3_arms.txt'
```

---

## 4. The result that matters, and why it needs checking before publication

Accuracy on real prose (2,492 narratives, surrogate-filled, 3 seeds each):

| arm | params | recall | precision | F1 | GPU ms |
|---|---:|---:|---:|---:|---:|
| **micro** | 70.7M | **76.0% ±0.8** | 97.6% | **85.5% ±0.5** | 5 |
| base | 184M | 68.0% ±3.6 | 97.3% | 80.0% ±2.9 | 7 |
| large | 434M | 68.2% ±2.6 | 97.0% | 80.1% ±1.8 | 18 |

**The smallest model wins**, by ~5 F1, at a third of large's cost, with the tightest variance.
That is the opposite of the prediction and a strong result for the portfolio's thesis — which is
exactly why it should be attacked before it is published.

**Two things to check first:**

1. **base scored 68.0% here but 70.5% in the previous run** — same architecture, *better* training
   data (more real carriers), slightly worse result. That contradicts the clean "better carriers →
   better model" story from M3's earlier round. Do not paper over it.
2. **Is micro's win real or an artefact?** Candidates: 15,000 examples underdetermine 434M
   parameters; or the larger models overfit the injected distribution and transfer worse. Both
   testable. Neither established.

Throughput (measured on the GPU, `results/m3_throughput.txt` — **this one is confirmed good**):

| arm | per sec | 300k complaints | $/1,000 |
|---|---:|---:|---:|
| micro | 192 | 0.43 hrs | $0.00027 |
| base | 155 | 0.54 hrs | $0.00034 |
| large | 63 | 1.32 hrs | $0.00084 |

---

## 5. Still owed

- **Writer arm**: accuracy + drift (drift measurement is built and unit-tested in
  `scripts/m3_predict_generative.py`; drifted output scores as redacting nothing, per decision 006)
- **M5 utility**: `scripts/m5_utility.py` works and is smoke-tested. Key is in `.secrets/env`
  (gitignored). Run `--n 250 --methods raw,presidio,airlock,spacy`. Note `relief` scored 0% even
  on raw text in the smoke test — likely a bad question (the outcome is recorded after the fact
  and often is not in the narrative). Check, and drop it with a reason if so.
- **`make repro`** has never been run end to end from a clean checkout. The constitution requires
  it.
- **`docs/01-why.md`, `02-data.md`, `06-utility.md`** are still stubs.
- **`make prune-superseded`** once the new arms replace the old — reclaims 4.2GB.
- **Fix the writer trainer's efficiency** before quoting its training cost: 40% of compute went to
  padding, gradient checkpointing was on with 17GB of VRAM free, batch was 2. The "13x slower to
  train" figure is inflated by my implementation; the fair number is ~4x. The **inference** gap is
  real and architectural.

---

## 6. Failure modes from this session — worth not repeating

Four bugs, one root cause each, all of which produced *plausible* output:

1. **`pkill -f PATTERN` over SSH matches its own command line.** Caused three zombie watchers and
   one kill that would have failed silently. Use `pkill -f "[P]ATTERN"`.
2. **Piping an unverified command through `grep`/`tail` hides its failure.** The remote `pip
   install` did nothing and reported success; `m3_throughput.py` printed its header and died on a
   missing file. Both looked fine.
3. **Scripts written after the last `rsync` do not exist on the remote.** Sync before invoking.
4. **A script written for the M1 silently fell back to CPU on the GPU box.** `m3_compare_arms.py`
   checked `mps` and never `cuda`; the eval ran with the card at 0% utilisation.

And the process failure that cost the money: **`finish_run.sh` never contained the accuracy step
at all.** It was described as "step 1 of the plan" in three messages and implemented in none. A
plan described is not a plan scheduled — check the script, not the intent.
