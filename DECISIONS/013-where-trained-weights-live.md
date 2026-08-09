# 013 — Trained weights move to S3, and why the storage tier does not matter

**Date:** 2026-08-09
**Status:** Decided by the human, on evidence gathered 2026-08-09.
**Blocks:** GPU teardown, M5, `make repro`

---

## The problem

Nine trained arms (7.81 GB) existed only on a rented vast.ai instance billing
$0.19/hr. Getting them off had already failed repeatedly: `rsync`, even with
`--partial-dir` and retries, died with "broken pipe" / "unexpected end of file"
on every file over ~300 MB. The instance had been up 18.1 hours (~$3.44) largely
because nothing had succeeded in emptying it.

The question put was whether **S3 would work better than pulling to the laptop**,
and whether **cold storage** was worth considering over hot.

## What was measured, before choosing

| path | throughput |
|---|---|
| box → laptop, one SSH stream | 0.89 MB/s, **truncated silently at 148 MB of a 300 MB read** |
| box → Cloudflare, one stream | 0.42 MB/s |
| box → Cloudflare, six streams | **~2.0 MB/s aggregate** |

The instance advertises 192 Mbit/s up (24 MB/s) and delivered roughly 2% of that
per stream.

**The bottleneck was the box's uplink, not the protocol and not the
destination.** That reframes the original question: S3 is not better *because it
is S3*. It is better because multipart upload is parallel and each part retries
independently, and parallelism is the only lever that moved the number. `rsync`
failed because it multiplexes one logical stream over SSH — one stall loses the
whole file.

The silent truncation is worth naming separately: `ssh 'dd ...' > file` returned
success having written 148 MB of 300 MB. That is failure mode #2 from the
previous session (an unverified command hidden behind a pipe) recurring in a new
place, and it is why transfers are now verified by size and by sha256 rather
than by exit code.

## Cold vs hot: the question is economically null at this volume

7.81 GB, us-east-1:

| tier | $/month | $/year | minimum billing | restore |
|---|---:|---:|---|---|
| **Standard** | **$0.167** | **$2.00** | none | instant |
| Standard-IA | $0.091 | $1.09 | 30 days | instant + $0.01/GB |
| Glacier Instant | $0.029 | $0.35 | 90 days | instant + $0.03/GB |
| Glacier Flexible | $0.026 | $0.31 | 90 days | mins–12 h |
| Deep Archive | $0.007 | $0.09 | 180 days | 12–48 h |

The largest available saving is **$1.91/year**. For scale: the GPU being emptied
costs **$0.19/hour**, so one hour of it pays for a month of hot storage of every
weight in the project, and the 18.1 idle hours already spent would have paid for
roughly 20 months.

**Chosen: S3 Standard, no lifecycle tiering.** The cold tiers are not merely
pointless here, they are worse:

1. Their 90- and 180-day minimum billing commitments probably exceed the
   artifacts' useful life — every model is rebuildable for ~$1.20 of GPU time.
2. A 12–48 hour restore obstructs precisely the work that comes next, which is
   attacking the micro-beats-large result. Weights you cannot open for two days
   are weights you will not check.

Egress is **$0** in practice: AWS gives 100 GB/month of free internet egress and
a full retrieval is 7.81 GB.

Where tiering would actually save money is *expiry*, not transition. That was
offered and not taken; if these are still sitting in S3 after the portfolio is
finished, deleting them is the lever, not moving them to Glacier.

## Credentials

**No AWS credential goes onto rented hardware.** `scripts/s3_stage_weights.py`
signs a presigned URL per part locally, using `~/.aws/credentials` via boto3; the
box receives only time-limited URLs and uploads with `curl`. `rclone` is already
installed on the instance and would have been simpler, but it needs real
credentials, so it was not used.

The generated manifest contains those presigned URLs, which are write
capabilities for the bucket. It is written to `.secrets/` (gitignored), never to
`results/`, which is committed.

The bucket (named via `AIRLOCK_S3_BUCKET`, kept out of the repository because the
name embeds an AWS account id) has public access blocked and SSE-AES256 on.

## Consequences

1. **This satisfies backup, not publication.** [Decision 011](011-training-moves-to-rented-gpu.md)
   commits `make repro` to *publishing* trained weights so evaluation and attack
   numbers regenerate without retraining — "a repro that silently requires a
   rented A100 is not a repro". A private bucket does not meet that. Whether the
   weights go to a public bucket, to the Hugging Face Hub, or whether the repro
   path accepts retraining, is an open fork and is **not** settled by this file.
2. Transfer is verified by size and sha256 against the source, not by exit code.
3. The upload runs concurrently with GPU work, so it consumes no additional
   rental time.
