#!/usr/bin/env python
"""Move the trained weights off the rented GPU box into S3, without ever putting
an AWS credential on that box.

Why this exists
---------------
rsync and plain `ssh cat` both die partway through the 710MB and 1.7GB
safetensors files. Measured on 2026-08-09, the cause is not the protocol:

    box -> laptop, 1 SSH stream    0.89 MB/s   (truncated silently at 148MB)
    box -> Cloudflare, 1 stream    0.42 MB/s
    box -> Cloudflare, 6 streams   ~2.0 MB/s aggregate

The instance advertises 192 Mbit/s up and delivers about 2% of that per stream.
Parallelism is the only lever that works, so the transfer is done as an S3
multipart upload: 64MiB parts, six at a time, each part retried on its own. A
dropped connection costs one part, not one file.

How the credential stays on this laptop
---------------------------------------
boto3 signs a presigned URL per part using ~/.aws/credentials locally. The box
receives only time-limited URLs and uploads with curl. No key material is
transmitted to, or stored on, rented hardware.

Completion needs each part's ETag. Rather than have the box report them back
(another thing to get wrong), we ask S3 directly with list_parts -- which also
makes the whole run resumable: parts already in S3 are simply not re-uploaded.

Usage
-----
    scripts/s3_stage_weights.py plan     # presign, write manifest, print size
    scripts/s3_stage_weights.py complete # finish multipart uploads, verify
    scripts/s3_stage_weights.py status   # what has landed so far
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.config import Config

# The published bucket. Named so it carries no account identifier -- the
# original was `airlock-weights-<account-id>`, which is why this is overridable
# and why the name is checked rather than assumed.
BUCKET = os.environ.get("AIRLOCK_PUBLIC_BUCKET", "airlock-redaction")
PROFILE = "default"
REGION = "us-east-1"
PREFIX = "m3"

# The rented box this was written for is destroyed and its address has been
# reassigned to someone else, so nothing here is hardcoded. Set these if you
# ever need to drain another rented instance.
REMOTE_ROOT = os.environ.get("AIRLOCK_REMOTE_ROOT", "/workspace/airlock")
SSH_KEY = os.environ.get("AIRLOCK_SSH_KEY", str(Path.home() / ".ssh" / "airlock_vast"))
SSH_PORT = os.environ.get("AIRLOCK_SSH_PORT", "22")
SSH_HOST = os.environ.get("AIRLOCK_SSH_HOST", "")

PART_SIZE = 64 * 1024 * 1024  # S3 minimum is 5MiB; 64 keeps the part count low.
URL_TTL = 12 * 60 * 60  # Long enough to survive a slow overnight transfer.
SINGLE_PUT_MAX = PART_SIZE  # Below this, one PUT is simpler than a multipart.

MODELS = [
    "encoder-micro-s20260808",
    "encoder-base2-s20260806",
    "encoder-base2-s20260807",
    "encoder-base2-s20260808",
    "encoder-large-s20260806",
    "encoder-large-s20260807",
    "encoder-large-s20260808",
    "generative-s20260806",
]

# The manifest holds presigned URLs. Those are time-limited write capabilities
# for the bucket, so they live in .secrets/ (gitignored) and never in results/,
# which is committed.
MANIFEST = Path(__file__).resolve().parent.parent / ".secrets" / "s3_upload_manifest.json"

SSH = [
    "ssh", "-i", SSH_KEY, "-p", SSH_PORT,
    "-o", "ConnectTimeout=20", "-o", "StrictHostKeyChecking=accept-new",
    "-o", "LogLevel=ERROR", SSH_HOST,
]


def ssh(cmd: str) -> str:
    """Run a command on the box and return stdout, raising if it failed.

    Requires AIRLOCK_SSH_HOST; there is no default host to fall back to.

    Deliberately not piped through grep/tail: a previous session lost hours to a
    remote command that failed while its pipeline reported success.
    """
    if not SSH_HOST:
        sys.exit("set AIRLOCK_SSH_HOST (e.g. root@1.2.3.4) — no default host")
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed ({r.returncode}): {cmd}\n{r.stderr}")
    return r.stdout


def _require_bucket() -> None:
    if not BUCKET:
        sys.exit("set AIRLOCK_PUBLIC_BUCKET")


def s3_client():
    _require_bucket()
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    # s3v4 + virtual addressing keeps the presigned URLs valid for 12 hours.
    return session.client("s3", config=Config(signature_version="s3v4"))


def remote_inventory() -> list[dict]:
    """Ask the box what is actually in each model directory, with sizes.

    The layouts differ -- the generative arm is a LoRA adapter, not an encoder --
    so nothing here assumes a filename.
    """
    listing = ssh(
        "cd %s/models && for d in %s; do "
        "  for f in \"$d\"/*; do [ -f \"$f\" ] && stat -c '%%n %%s' \"$f\"; done; "
        "done" % (REMOTE_ROOT, " ".join(MODELS))
    )
    files = []
    for line in listing.splitlines():
        line = line.strip()
        if not line:
            continue
        name, size = line.rsplit(" ", 1)
        files.append({
            "rel": name,
            "remote": f"{REMOTE_ROOT}/models/{name}",
            "key": f"{PREFIX}/models/{name}",
            "size": int(size),
        })
    return files


def cmd_plan() -> None:
    s3 = s3_client()
    files = remote_inventory()
    jobs, uploads, total, skipped = [], [], 0, 0

    for f in files:
        # Already uploaded and the right size? Leave it alone.
        try:
            head = s3.head_object(Bucket=BUCKET, Key=f["key"])
            if head["ContentLength"] == f["size"]:
                skipped += 1
                continue
        except s3.exceptions.ClientError:
            pass

        total += f["size"]

        if f["size"] <= SINGLE_PUT_MAX:
            url = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": f["key"]},
                ExpiresIn=URL_TTL,
            )
            jobs.append({
                "id": f["key"].replace("/", "_") + ".single",
                "model": f["rel"].split("/")[0],
                "src": f["remote"], "offset": 0, "length": f["size"], "url": url,
            })
            continue

        # Multipart. Reuse an in-flight upload if one exists, so a re-run
        # resumes instead of starting over.
        existing = s3.list_multipart_uploads(Bucket=BUCKET, Prefix=f["key"]).get("Uploads", [])
        match = [u for u in existing if u["Key"] == f["key"]]
        if match:
            upload_id = sorted(match, key=lambda u: u["Initiated"])[-1]["UploadId"]
        else:
            upload_id = s3.create_multipart_upload(Bucket=BUCKET, Key=f["key"])["UploadId"]

        done = {
            p["PartNumber"]
            for p in s3.list_parts(Bucket=BUCKET, Key=f["key"], UploadId=upload_id).get("Parts", [])
        }

        n_parts = (f["size"] + PART_SIZE - 1) // PART_SIZE
        uploads.append({"key": f["key"], "upload_id": upload_id, "n_parts": n_parts})

        for i in range(n_parts):
            part_no = i + 1
            if part_no in done:
                continue
            offset = i * PART_SIZE
            length = min(PART_SIZE, f["size"] - offset)
            url = s3.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": BUCKET, "Key": f["key"],
                    "UploadId": upload_id, "PartNumber": part_no,
                },
                ExpiresIn=URL_TTL,
            )
            jobs.append({
                "id": f"{f['key'].replace('/', '_')}.p{part_no:05d}",
                "model": f["rel"].split("/")[0],
                "src": f["remote"], "offset": offset, "length": length, "url": url,
            })

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"bucket": BUCKET, "uploads": uploads, "jobs": jobs}, indent=1))

    # The worker on the box has no JSON parser worth relying on, so it gets a
    # tab-separated view of the same jobs.
    #
    # Order by how much each MODEL has left, smallest first. A model is only
    # usable when every one of its files is in, so finishing the nearly-complete
    # ones first maximises the number of whole, loadable models per megabyte.
    # That is the right objective because the documented fallback is to destroy
    # the box with the transfer unfinished -- in which case what matters is how
    # many models survive, not how many bytes moved. (An earlier version sorted
    # largest-part-first, which is the opposite: it started the three 1.7GB
    # models and left four others one part short of done.)
    tsv = MANIFEST.with_suffix(".tsv")
    left = {}
    for j in jobs:
        left[j["model"]] = left.get(j["model"], 0) + j["length"]
    ordered = sorted(jobs, key=lambda j: (left[j["model"]], j["model"], j["id"]))
    tsv.write_text(
        "".join(
            f"{j['id']}\t{j['src']}\t{j['offset']}\t{j['length']}\t{j['url']}\n"
            for j in ordered
        )
    )

    pending = sum(j["length"] for j in jobs)
    print(f"files already complete in S3 : {skipped}")
    print(f"multipart uploads open       : {len(uploads)}")
    print(f"jobs to run                  : {len(jobs)}")
    print(f"bytes to move                : {pending/1e9:.2f} GB")
    print(f"est. at 2.0 MB/s aggregate   : {pending/2e6/60:.0f} min")
    print(f"manifest                     : {MANIFEST}")


def cmd_complete() -> None:
    s3 = s3_client()
    manifest = json.loads(MANIFEST.read_text())
    failures = []

    for up in manifest["uploads"]:
        # A manifest can outlive its uploads: re-running `complete` after an
        # earlier one finished some files leaves stale UploadIds behind. That is
        # a no-op, not an error -- the object either exists or the verification
        # pass below will catch that it does not.
        try:
            parts = s3.list_parts(Bucket=BUCKET, Key=up["key"],
                                  UploadId=up["upload_id"]).get("Parts", [])
        except s3.exceptions.NoSuchUpload:
            print(f"  already finalised  {up['key']}")
            continue
        have = sorted(p["PartNumber"] for p in parts)
        if len(have) != up["n_parts"]:
            missing = sorted(set(range(1, up["n_parts"] + 1)) - set(have))
            print(f"  incomplete {up['key']}: {len(have)}/{up['n_parts']} parts, missing {missing[:8]}...")
            failures.append(up["key"])
            continue
        s3.complete_multipart_upload(
            Bucket=BUCKET, Key=up["key"], UploadId=up["upload_id"],
            MultipartUpload={
                "Parts": [
                    {"PartNumber": p["PartNumber"], "ETag": p["ETag"]}
                    for p in sorted(parts, key=lambda p: p["PartNumber"])
                ]
            },
        )
        print(f"  completed  {up['key']}")

    print("\n--- verifying sizes against the box ---")
    for f in remote_inventory():
        try:
            head = s3.head_object(Bucket=BUCKET, Key=f["key"])
        except s3.exceptions.ClientError:
            print(f"  MISSING {f['key']}")
            failures.append(f["key"])
            continue
        ok = head["ContentLength"] == f["size"]
        print(f"  {'ok  ' if ok else 'BAD '} {f['key']}  {head['ContentLength']} vs {f['size']}")
        if not ok:
            failures.append(f["key"])

    if failures:
        print(f"\nINCOMPLETE: {len(failures)} objects", file=sys.stderr)
        sys.exit(1)
    print("\nAll objects present in S3 at the expected size.")


def cmd_status() -> None:
    s3 = s3_client()
    total_done = 0
    for f in remote_inventory():
        try:
            head = s3.head_object(Bucket=BUCKET, Key=f["key"])
            total_done += head["ContentLength"]
            print(f"  done    {f['key']}")
            continue
        except s3.exceptions.ClientError:
            pass
        ups = [
            u for u in s3.list_multipart_uploads(Bucket=BUCKET, Prefix=f["key"]).get("Uploads", [])
            if u["Key"] == f["key"]
        ]
        if not ups:
            print(f"  pending {f['key']}")
            continue
        uid = sorted(ups, key=lambda u: u["Initiated"])[-1]["UploadId"]
        parts = s3.list_parts(Bucket=BUCKET, Key=f["key"], UploadId=uid).get("Parts", [])
        got = sum(p["Size"] for p in parts)
        total_done += got
        n = (f["size"] + PART_SIZE - 1) // PART_SIZE
        print(f"  {len(parts):3d}/{n:3d} parts  {got/1e6:8.0f}/{f['size']/1e6:8.0f} MB  {f['key']}")
    print(f"\ntransferred so far: {total_done/1e9:.2f} GB")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "plan"
    {"plan": cmd_plan, "complete": cmd_complete, "status": cmd_status}[action]()
