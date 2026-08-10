# 018 — The weights are published, and `make repro` is unblocked

**Date:** 2026-08-09
**Status:** Decided by the human. Supersedes the storage arrangement in
[decision 013](013-where-trained-weights-live.md).
**Blocks:** `make repro`, README

---

## What changed

[Decision 013](013-where-trained-weights-live.md) put the trained weights in a
**private** bucket named `airlock-weights-<account-id>`. It said so at the time:

> This satisfies backup, not publication. […] A private bucket does not meet
> that. Whether the weights go to a public bucket, to the Hugging Face Hub, or
> whether the repro path accepts retraining, is an open fork.

That fork is now closed. Everything lives in one **public, read-only** bucket:

    s3://airlock-redaction/

| prefix | size | contents |
|---|---:|---|
| `m3/models/` | 7.3 GiB | the ten trained arms |
| `data/synthetic/` | 85 MiB | injected sets — what the models trained on |
| `data/interim/` | 138 MiB | filtered credit-card narratives |
| `data/raw/` | 8.4 GiB | the pinned CFPB snapshot + `PROVENANCE.txt` |
| `results/` | 305 KiB | every results file and run log |

Anonymous, no AWS account required:

```bash
aws s3 sync s3://airlock-redaction/m3/models models --no-sign-request
curl -O https://airlock-redaction.s3.amazonaws.com/results/m5_utility.txt
```

`scripts/fetch_weights.sh` wraps this.

## Why this specific shape

**Why a new bucket rather than opening the old one.** The old name embedded an
AWS account id. That is not a secret, but it is gratuitous in a repository meant
to be read by strangers, and it forced the bucket name to be an environment
variable instead of a committed default. `airlock-redaction` carries no
identifier, so it is hardcoded and the repo is self-contained.

The literal name `airlock` was not available — S3 bucket names are globally
unique across all AWS accounts and it is already taken by someone else.

**Why one bucket and not two.** Keeping the private original alongside the
public copy would have paid twice to store identical bytes. The original was
deleted after the copy was verified.

**Why the raw corpus is included, at 8.4 GiB of the 15.9.** It is the only
artifact in the project that cannot be regenerated: `bootstrap.sh` fetches a
rolling URL with no versioning, so the 2026-08-06 snapshot ceases to exist the
moment the CFPB republishes. Every number here was computed from those exact
bytes. Publishing it is the only way the numbers are checkable by anyone else,
which is what constitution principle III actually asks for.

## Verification before the original was deleted

Deleting the only other copy of an irreplaceable file deserves more than an exit
code:

- 157/157 objects present, byte totals equal
- `encoder-base2-s20260806` and `encoder-micro-s20260808` sha256 re-verified
  against the values taken from the GPU box before it was destroyed
- `encoder-large-s20260806` (1.7 GB, 26 parts) hashed in both buckets: identical
- `complaints.csv` streamed and hashed: matches `PROVENANCE.txt`
- an anonymous, credential-free download proven to work

**ETags differ between the buckets for the nine multipart objects, and that is
expected, not corruption.** A multipart ETag is a hash-of-hashes plus a part
count, and a server-side copy re-chunks with different boundaries. Sizes and
sha256 are the checks that mean anything here; ETag equality would have been the
wrong thing to look for.

## The cost exposure, stated plainly

A public bucket has **no spending limit**, and S3 offers no hard cap. 100 GB of
egress per month is free, then $0.09/GB — so roughly six full downloads of the
16 GB before charges begin. A crawler or a popular link could bill far more,
with no warning until the invoice.

Two guards, and it is worth being clear about which does what:

1. **Budget `airlock-s3-guard`**, $5/month scoped to S3, emailing at 50% actual,
   100% actual, and 100% forecast. This *notifies*. It does not stop anything.
2. **`scripts/s3_public_killswitch.sh off`** revokes the public policy and
   re-arms the account-level public-access block, immediately. This is what
   actually stops it.

An alarm without a rehearsed response is only a faster way to learn about a
bill, which is why the switch is committed rather than described.

**CloudFront was considered and rejected.** Fronting a bucket that is *also*
directly readable caps nothing, because anyone can bypass the CDN by addressing
S3. A real choke point requires making the bucket private and serving only
through CloudFront — which contradicts the requirement that the bucket be
publicly readable. Building it anyway would have produced a component whose name
implied a protection it did not provide.

## Privacy

Checked rather than assumed, since the point of the rename was to expose
nothing:

- bucket policy contains no account id (an earlier draft used an
  `aws:PrincipalAccount` condition for defence in depth; it was removed, since
  S3 denies by default and the statement bought nothing but an identifier)
- `?policy` and `?acl` return 403 to anonymous callers
- no account id in anonymous LIST bodies or response headers
- `PROVENANCE.txt` rewritten — the copy in the old bucket still referenced the
  account-id-named bucket in its `archived_to:` line
- models, configs, results and docs scanned for username, email, home paths,
  credentials and the GPU host IP: none present

## Consequences

1. **`make repro` is unblocked.** It can fetch published weights instead of
   retraining, which is what decision 011 required — "a repro that silently
   requires a rented A100 is not a repro". Wiring it up is still to do.
2. The bucket name is a committed default, so the repository is self-contained.
3. If the weights are ever withdrawn, `make repro` must fall back to
   `scripts/train_all_seeds.sh` and the README must say so.
